"""
Jobs API routes.

GET /jobs        — list all jobs with match scores
GET /jobs/{id}   — get a single job
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


from app.database.database import get_db
from app.database.models import Job, JobMatch, SentJob

logger = logging.getLogger(__name__)
router = APIRouter()


def serialize_job(job: Job) -> Dict[str, Any]:
    """Serialize a Job ORM object to a response dict."""
    match = job.match
    sent = job.sent_record

    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "work_mode": job.work_mode,
        "salary_raw": job.salary_raw,
        "salary_min_inr": job.salary_min_inr,
        "salary_max_inr": job.salary_max_inr,
        "experience_min_years": job.experience_min_years,
        "experience_max_years": job.experience_max_years,
        "experience_raw": job.experience_raw,
        "employment_type": job.employment_type,
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "description": job.description,
        "posted_date": job.posted_date.isoformat() if job.posted_date else None,
        "application_url": job.application_url,
        "job_url": job.job_url,
        "linkedin_url": job.linkedin_url,
        "source": job.source,
        "discovered_at": job.discovered_at.isoformat(),
        "emailed": sent is not None,
        "email_sent_at": sent.email_sent_at.isoformat() if sent else None,
        # Match info
        "match_score": match.total_score if match else None,
        "match_category": match.match_category if match else None,
        "match_reasons": match.match_reasons if match else [],
        "gaps": match.gaps if match else [],
        "skills_matched": match.skills_matched if match else [],
        "skills_missing": match.skills_missing if match else [],
    }


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    min_score: Optional[int] = Query(default=None),
    emailed_only: bool = Query(default=False),
    source: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    List discovered jobs with optional filters.
    Results sorted by discovery date/time (newest first), then match score.
    """
    query = select(Job).options(selectinload(Job.match), selectinload(Job.sent_record))
    count_query = select(func.count(Job.id))

    if min_score is not None:
        query = query.join(JobMatch, Job.id == JobMatch.job_id).where(
            JobMatch.total_score >= min_score
        )
        count_query = count_query.join(JobMatch, Job.id == JobMatch.job_id).where(
            JobMatch.total_score >= min_score
        )
        query = query.order_by(desc(Job.discovered_at), desc(JobMatch.total_score))
    else:
        query = query.order_by(desc(Job.discovered_at))

    if emailed_only:
        query = query.join(SentJob, Job.id == SentJob.job_id)
        count_query = count_query.join(SentJob, Job.id == SentJob.job_id)

    if source:
        query = query.where(Job.source == source)
        count_query = count_query.where(Job.source == source)

    total_count = (await db.scalar(count_query)) or 0

    total_matched_count = (await db.scalar(
        select(func.count(Job.id))
        .join(JobMatch, Job.id == JobMatch.job_id)
        .where(JobMatch.total_score >= 70)
    )) or 0

    total_all_count = (await db.scalar(
        select(func.count(Job.id))
    )) or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    jobs = result.scalars().all()

    serialized = [serialize_job(j) for j in jobs]

    return {
        "total": total_count,
        "total_matched": total_matched_count,
        "total_all": total_all_count,
        "offset": offset,
        "limit": limit,
        "jobs": serialized,
    }





@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single job by ID."""
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.match), selectinload(Job.sent_record))
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return serialize_job(job)
