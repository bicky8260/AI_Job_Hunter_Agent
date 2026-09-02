"""
Database cleanup module for automated retention management.
Deletes jobs, match scores, sent records, and search runs older than retention threshold (default 10 days).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Job, SearchRun

logger = logging.getLogger(__name__)


async def cleanup_expired_data(
    db: AsyncSession, retention_days: int = None
) -> Dict[str, Any]:
    """
    Delete jobs and search runs older than retention_days.

    Cascading foreign keys in PostgreSQL/SQLite automatically remove associated
    JobMatch and SentJob records when a Job is deleted.

    Returns stats dict: {"deleted_jobs": int, "deleted_runs": int}
    """
    if retention_days is None:
        retention_days = get_settings().job_retention_days

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    try:
        # Delete old jobs (Cascades to job_matches & sent_jobs)
        job_result = await db.execute(
            delete(Job).where(Job.discovered_at < cutoff)
        )
        deleted_jobs = job_result.rowcount if job_result.rowcount is not None else 0

        # Delete old search runs
        run_result = await db.execute(
            delete(SearchRun).where(SearchRun.started_at < cutoff)
        )
        deleted_runs = run_result.rowcount if run_result.rowcount is not None else 0

        await db.commit()

        if deleted_jobs > 0 or deleted_runs > 0:
            logger.info(
                f"Data cleanup completed ({retention_days}-day policy): "
                f"purged {deleted_jobs} old jobs and {deleted_runs} old search runs (cutoff: {cutoff.isoformat()})"
            )
        else:
            logger.debug(f"Data cleanup: no records older than {retention_days} days to purge")

        return {
            "status": "success",
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "deleted_jobs": deleted_jobs,
            "deleted_runs": deleted_runs,
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to execute database cleanup: {e!r}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "deleted_jobs": 0,
            "deleted_runs": 0,
        }
