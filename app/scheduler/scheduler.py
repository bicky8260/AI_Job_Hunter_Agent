"""
APScheduler-based daily job search scheduler.

- Runs once per day at configured time (default 09:00 AM IST)
- Checks agent.enabled before running
- Uses Asia/Kolkata timezone
- Handles machine downtime gracefully (missed runs are logged, not retried)
- Schedule time is configurable via environment variables
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the global scheduler instance, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def _run_scheduled_search():
    """Called by APScheduler at the configured daily time."""
    try:
        from app.agents.job_agent import JobAgent
        logger.info("=== Scheduled job search triggered ===")
        agent = JobAgent()
        result = await agent.run(triggered_by="scheduler")
        logger.info(f"Scheduled run completed: {result}")
    except Exception as e:
        logger.error(f"Scheduled job search failed: {e!r}", exc_info=True)


def start_scheduler():
    """
    Start the APScheduler with the daily job search job.
    Should be called once at application startup.
    """
    settings = get_settings()
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("Scheduler already running")
        return

    tz = pytz.timezone(settings.scheduler_timezone)

    scheduler.add_job(
        _run_scheduled_search,
        trigger=CronTrigger(
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
            timezone=tz,
        ),
        id="daily_job_search",
        name="Daily Job Search",
        replace_existing=True,
        misfire_grace_time=3600,  # allow up to 1 hour late (handles machine sleep)
        coalesce=True,  # only run once even if multiple triggers missed
    )

    scheduler.start()

    next_run = scheduler.get_job("daily_job_search").next_run_time
    logger.info(
        f"Scheduler started — next run: {next_run} "
        f"({settings.scheduler_timezone} {settings.scheduler_hour:02d}:{settings.scheduler_minute:02d})"
    )

    # Update next_scheduled_run in DB
    asyncio.ensure_future(_update_next_run_in_db(next_run))


def stop_scheduler():
    """Stop the APScheduler."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_next_run_time() -> Optional[datetime]:
    """Return the next scheduled run time."""
    scheduler = get_scheduler()
    if not scheduler.running:
        return None
    job = scheduler.get_job("daily_job_search")
    return job.next_run_time if job else None


async def _update_next_run_in_db(next_run: Optional[datetime]):
    """Store the next scheduled run time in AgentState."""
    try:
        from sqlalchemy import select
        from app.database.database import get_db_context
        from app.database.models import AgentState

        async with get_db_context() as db:
            result = await db.execute(select(AgentState).where(AgentState.id == 1))
            state = result.scalar_one_or_none()
            if state:
                state.next_scheduled_run = next_run
    except Exception as e:
        logger.debug(f"Could not update next_run in DB: {e!r}")
