"""
Agent control API routes.

GET  /agent/status  — current state
POST /agent/start   — enable agent
POST /agent/stop    — disable agent
POST /agent/search  — trigger manual search
GET  /health        — health check
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.database import get_db
from app.database.models import AgentState, Job, SearchRun, SentJob
from app.scheduler.scheduler import get_next_run_time

logger = logging.getLogger(__name__)
router = APIRouter()

# Track running search to prevent concurrent runs
_search_running = False


async def get_or_create_state(db: AsyncSession) -> AgentState:
    result = await db.execute(select(AgentState).where(AgentState.id == 1))
    state = result.scalar_one_or_none()
    if state is None:
        state = AgentState(id=1, enabled=False)
        db.add(state)
        await db.flush()
    return state


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/agent/status")
async def get_agent_status(db: AsyncSession = Depends(get_db)):
    """Return current agent status and statistics."""
    state = await get_or_create_state(db)

    # Get stats
    total_jobs = await db.scalar(select(func.count(Job.id)))
    total_sent = await db.scalar(select(func.count(SentJob.id)))

    # Get last run info
    last_run_result = await db.execute(
        select(SearchRun)
        .where(SearchRun.status.in_(["completed", "failed"]))
        .order_by(SearchRun.started_at.desc())
        .limit(1)
    )
    last_run = last_run_result.scalar_one_or_none()

    next_run = get_next_run_time()

    response: Dict[str, Any] = {
        "enabled": state.enabled,
        "status": "RUNNING" if state.enabled else "STOPPED",
        "last_started_at": state.last_started_at.isoformat() if state.last_started_at else None,
        "last_stopped_at": state.last_stopped_at.isoformat() if state.last_stopped_at else None,
        "last_successful_run": state.last_successful_run.isoformat() if state.last_successful_run else None,
        "next_scheduled_run": next_run.isoformat() if next_run else None,
        "total_jobs_tracked": total_jobs or 0,
        "total_jobs_sent": total_sent or 0,
        "search_running": _search_running,
    }

    if last_run:
        response["last_run"] = {
            "started_at": last_run.started_at.isoformat(),
            "status": last_run.status,
            "total_found": last_run.total_found,
            "total_matched": last_run.total_matched,
            "total_emailed": last_run.total_emailed,
            "triggered_by": last_run.triggered_by,
        }

    return response


@router.post("/agent/start")
async def start_agent(db: AsyncSession = Depends(get_db)):
    """Enable the agent. It will search from this point onward."""
    state = await get_or_create_state(db)

    if state.enabled:
        return {"message": "Agent is already running", "status": "RUNNING"}

    state.enabled = True
    state.last_started_at = datetime.now(timezone.utc)

    logger.info("Agent STARTED")
    return {
        "message": "Agent started successfully",
        "status": "RUNNING",
        "started_at": state.last_started_at.isoformat(),
    }


@router.post("/agent/stop")
async def stop_agent(db: AsyncSession = Depends(get_db)):
    """Disable the agent. No searches or emails will run."""
    state = await get_or_create_state(db)

    if not state.enabled:
        return {"message": "Agent is already stopped", "status": "STOPPED"}

    state.enabled = False
    state.last_stopped_at = datetime.now(timezone.utc)

    logger.info("Agent STOPPED")
    return {
        "message": "Agent stopped successfully",
        "status": "STOPPED",
        "stopped_at": state.last_stopped_at.isoformat(),
    }


async def _run_search_background():
    """Run search in background task."""
    global _search_running
    _search_running = True
    try:
        from app.agents.job_agent import JobAgent
        agent = JobAgent()
        result = await agent.run(triggered_by="manual")
        logger.info(f"Manual search completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Manual search failed: {e!r}", exc_info=True)
    finally:
        _search_running = False


@router.post("/agent/search")
async def trigger_search(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual job search immediately."""
    global _search_running

    state = await get_or_create_state(db)

    if not state.enabled:
        raise HTTPException(
            status_code=400,
            detail="Agent is stopped. Start the agent first to run a search.",
        )

    if _search_running:
        raise HTTPException(
            status_code=409,
            detail="A search is already running. Please wait for it to complete.",
        )

    background_tasks.add_task(_run_search_background)
    logger.info("Manual search triggered")

    return {
        "message": "Job search started in background",
        "status": "searching",
        "note": "Check /agent/status for results when complete",
    }


@router.get("/agent/runs")
async def get_search_runs(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Return recent search run history."""
    result = await db.execute(
        select(SearchRun).order_by(SearchRun.started_at.desc()).limit(limit)
    )
    runs = result.scalars().all()

    return [
        {
            "id": run.id,
            "triggered_by": run.triggered_by,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "status": run.status,
            "total_found": run.total_found,
            "total_matched": run.total_matched,
            "total_emailed": run.total_emailed,
            "total_rejected": run.total_rejected,
            "source_stats": run.source_stats,
            "error_message": run.error_message,
        }
        for run in runs
    ]


@router.post("/agent/test-email")
async def send_test_email_endpoint():
    """Send a test email to verify email configuration."""
    from app.notifications.email import send_test_email
    success = await send_test_email()
    if success:
        from app.config import get_settings
        settings = get_settings()
        mode = "saved to email_output/" if not settings.is_email_configured else f"sent to {settings.email_to}"
        return {"message": f"Test email {mode}", "success": True}
    return {"message": "Test email failed — check logs", "success": False}


@router.post("/agent/cleanup")
async def trigger_cleanup_endpoint(
    days: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Purge jobs and search runs older than retention threshold (default 10 days)."""
    from app.database.cleanup import cleanup_expired_data
    result = await cleanup_expired_data(db, retention_days=days)
    return result
