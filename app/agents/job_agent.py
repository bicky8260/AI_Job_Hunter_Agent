"""
Job Agent — the central orchestrator.

Responsibilities:
1. Check agent enabled state
2. Run all source adapters in parallel (with error isolation)
3. Deduplicate jobs (canonical hash + URL matching)
4. Filter already-sent jobs
5. Enrich and score jobs against resume
6. Filter jobs below minimum score
7. Store new jobs to database
8. Send email with matching jobs
9. Update run statistics
"""
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.config import get_job_preferences, get_search_settings, get_settings, reload_config_yaml
from app.database.database import get_db_context
from app.database.models import AgentState, Job, JobMatch, SearchRun, SentJob, ResumeData
from app.matching.matcher import JobMatcher, get_llm_provider
from app.notifications.email import send_job_email
from app.sources import get_all_sources
from app.sources.base import RawJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """Normalize job title for deduplication comparison."""
    title = title.lower().strip()
    # Remove common noise
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(
        r"\b(urgent|immediate|opening|vacancy|job|position|role|opportunity|hiring|required)\b",
        "",
        title,
    )
    return title.strip()


def normalize_company(company: str) -> str:
    """Normalize company name for deduplication."""
    company = company.lower().strip()
    company = re.sub(r"\b(pvt|ltd|limited|inc|llc|corp|corporation|technologies|tech|solutions|services)\b", "", company)
    company = re.sub(r"[^\w\s]", "", company)
    return re.sub(r"\s+", " ", company).strip()


def make_canonical_id(title: str, company: str, location: str, url: str) -> str:
    """
    Create a stable canonical job ID for deduplication.
    SHA256 hash of: normalized(title) + normalized(company) + location + domain(url)
    """
    # Extract domain from URL for URL-based dedup
    domain = ""
    if url:
        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if match:
            domain = match.group(1)
        # For job-specific URLs, use the full path (strip query params)
        path_match = re.search(r"https?://[^/]+(/.+?)(?:\?|#|$)", url)
        if path_match:
            domain = domain + path_match.group(1)

    canonical = "|".join([
        normalize_title(title),
        normalize_company(company),
        (location or "").lower().strip(),
        domain,
    ])
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def deduplicate_raw_jobs(jobs: List[RawJob]) -> List[RawJob]:
    """
    Remove duplicate jobs from a list.
    Keeps the job with the most information (longest description, LinkedIn URL, etc.).
    """
    seen_ids: Set[str] = set()
    seen_urls: Set[str] = set()
    unique: List[RawJob] = []

    for job in jobs:
        canonical_id = make_canonical_id(
            job.title, job.company,
            job.location or "",
            job.application_url or job.job_url or "",
        )

        # URL-based dedup
        url = (job.application_url or job.job_url or "").strip()

        if canonical_id in seen_ids or (url and url in seen_urls):
            # Try to merge LinkedIn URL into existing entry
            if url and job.linkedin_url:
                for existing in unique:
                    if existing.company.lower() == job.company.lower():
                        if not existing.linkedin_url:
                            existing.linkedin_url = job.linkedin_url
                        break
            continue

        seen_ids.add(canonical_id)
        if url:
            seen_urls.add(url)
        unique.append(job)

    return unique


# ---------------------------------------------------------------------------
# Job filtering
# ---------------------------------------------------------------------------

def passes_basic_filters(job: RawJob, preferences: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Quick filter before AI scoring.
    Returns (passes, reason_if_rejected).
    """
    title_lower = job.title.lower()

    # Check excluded titles
    for exc in preferences.get("exclude_titles", []):
        if exc.lower() in title_lower:
            return False, f"Excluded title: '{exc}'"

    # Check excluded keywords
    desc_lower = (job.description or "").lower()
    for kw in preferences.get("exclude_keywords", []):
        if kw.lower() in desc_lower or kw.lower() in title_lower:
            return False, f"Excluded keyword: '{kw}'"

    # Must be one of preferred titles OR description must mention DevOps-ish content
    preferred = [t.lower() for t in preferences.get("job_titles", [])]
    devops_terms = ["devops", "sre", "cloud engineer", "platform engineer", "infrastructure", "reliability"]

    title_match = any(t in title_lower for t in preferred + devops_terms)
    if not title_match:
        return False, f"Title '{job.title}' not relevant"

    return True, ""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def get_sent_job_ids(db_session) -> Set[str]:
    """Return set of canonical_ids already emailed."""
    result = await db_session.execute(
        select(Job.canonical_id).join(SentJob, Job.id == SentJob.job_id)
    )
    return {row[0] for row in result.fetchall()}


async def get_or_create_agent_state(db_session) -> AgentState:
    """Get or create the single AgentState row."""
    result = await db_session.execute(select(AgentState).where(AgentState.id == 1))
    state = result.scalar_one_or_none()
    if state is None:
        state = AgentState(id=1, enabled=False)
        db_session.add(state)
        await db_session.flush()
    return state


async def get_resume_profile(db_session) -> Dict[str, Any]:
    """Load resume profile from database."""
    result = await db_session.execute(select(ResumeData).where(ResumeData.id == 1))
    resume = result.scalar_one_or_none()
    if resume and resume.profile_json:
        return resume.profile_json
    # Return minimal profile if no resume uploaded
    return {
        "all_skills_flat": get_settings().__dict__.get("preferred_skills", []),
        "years_of_experience": 2.0,
        "cloud_platforms": [],
        "devops_tools": [],
    }


async def save_job_to_db(db_session, job: RawJob, canonical_id: str) -> Optional[Job]:
    """Save a raw job to the database. Returns the Job ORM object."""
    db_job = Job(
        canonical_id=canonical_id,
        title=job.title,
        company=job.company,
        location=job.location,
        work_mode=job.work_mode,
        salary_raw=job.salary_raw,
        salary_min_inr=job.salary_min_inr,
        salary_max_inr=job.salary_max_inr,
        salary_currency=job.salary_currency,
        experience_min_years=job.experience_min_years,
        experience_max_years=job.experience_max_years,
        experience_raw=job.experience_raw,
        employment_type=job.employment_type,
        required_skills=job.required_skills,
        preferred_skills=job.preferred_skills,
        description=job.description,
        posted_date=job.posted_date,
        application_deadline=job.application_deadline,
        application_url=job.application_url,
        job_url=job.job_url,
        company_url=job.company_url,
        linkedin_url=job.linkedin_url,
        source=job.source,
        source_job_id=str(job.source_job_id) if job.source_job_id is not None else None,
        raw_data=job.raw_data,
    )
    db_session.add(db_job)
    try:
        await db_session.flush()
        return db_job
    except IntegrityError:
        await db_session.rollback()
        # Job already exists — fetch it
        result = await db_session.execute(
            select(Job).where(Job.canonical_id == canonical_id)
        )
        return result.scalar_one_or_none()


async def save_match_to_db(db_session, job_id: str, match_result: Dict[str, Any]) -> None:
    """Save match score and reasoning to database."""
    match = JobMatch(
        job_id=job_id,
        total_score=match_result["total_score"],
        title_score=match_result.get("title_score", 0),
        skills_score=match_result.get("skills_score", 0),
        experience_score=match_result.get("experience_score", 0),
        location_score=match_result.get("location_score", 0),
        salary_score=match_result.get("salary_score", 0),
        relevance_score=match_result.get("relevance_score", 0),
        match_reasons=match_result.get("match_reasons", []),
        gaps=match_result.get("gaps", []),
        match_category=match_result.get("match_category", ""),
        skills_matched=match_result.get("skills_matched", []),
        skills_missing=match_result.get("skills_missing", []),
    )
    db_session.add(match)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

class JobAgent:
    """
    Main job search agent.
    Can be triggered manually or by the scheduler.
    """

    def __init__(self):
        self.settings = get_settings()
        self.matcher = JobMatcher(llm_provider=get_llm_provider())

    async def run(self, triggered_by: str = "scheduler") -> Dict[str, Any]:
        """
        Execute a full job search run.

        Returns run statistics dict.
        """
        run_id = None
        run_started = datetime.now(timezone.utc)

        async with get_db_context() as db:
            # ------------------------------------------------------------------
            # 1. Check agent state
            # ------------------------------------------------------------------
            state = await get_or_create_agent_state(db)

            if not state.enabled:
                logger.info(f"Agent is STOPPED — skipping run (triggered_by={triggered_by})")
                return {
                    "status": "skipped",
                    "reason": "Agent is stopped",
                    "total_found": 0,
                    "total_matched": 0,
                }

            logger.info(f"=== Job search run started (triggered_by={triggered_by}) ===")

            # ------------------------------------------------------------------
            # 2. Create SearchRun record
            # ------------------------------------------------------------------
            search_run = SearchRun(
                triggered_by=triggered_by,
                started_at=run_started,
                status="running",
            )
            db.add(search_run)
            await db.flush()
            run_id = search_run.id

            try:
                result = await self._execute_run(db, search_run)

                # Update run record
                search_run.status = "completed"
                search_run.completed_at = datetime.now(timezone.utc)
                search_run.total_found = result["total_found"]
                search_run.total_unique = result["total_unique"]
                search_run.total_matched = result["total_matched"]
                search_run.total_emailed = result["total_emailed"]
                search_run.total_duplicates = result["total_duplicates"]
                search_run.total_rejected = result["total_rejected"]
                search_run.source_stats = result["source_stats"]

                # Update agent state
                state.last_successful_run = datetime.now(timezone.utc)

                logger.info(
                    f"=== Run completed: found={result['total_found']}, "
                    f"matched={result['total_matched']}, emailed={result['total_emailed']} ==="
                )
                return result

            except Exception as e:
                logger.error(f"Run failed: {e!r}", exc_info=True)
                if search_run:
                    search_run.status = "failed"
                    search_run.error_message = str(e)
                    search_run.completed_at = datetime.now(timezone.utc)
                return {
                    "status": "failed",
                    "error": str(e),
                    "total_found": 0,
                    "total_matched": 0,
                }

    async def _execute_run(self, db, search_run: SearchRun) -> Dict[str, Any]:
        """Core run logic — called inside transaction."""
        # Reload config.yaml in case it was updated
        reload_config_yaml()
        preferences = get_job_preferences()
        search_settings = get_search_settings()
        min_score = search_settings.get("min_match_score", self.settings.min_match_score)

        # ------------------------------------------------------------------
        # 3. Get already-sent canonical IDs
        # ------------------------------------------------------------------
        sent_ids = await get_sent_job_ids(db)
        logger.info(f"Already sent: {len(sent_ids)} jobs")

        # ------------------------------------------------------------------
        # 4. Load resume profile
        # ------------------------------------------------------------------
        resume_profile = await get_resume_profile(db)

        # ------------------------------------------------------------------
        # 5. Run all sources in parallel
        # ------------------------------------------------------------------
        sources = get_all_sources(preferences, search_settings)
        logger.info(f"Running {len(sources)} source adapters")

        source_tasks = [source.safe_search() for source in sources]
        source_results = await asyncio.gather(*source_tasks, return_exceptions=True)

        all_jobs: List[RawJob] = []
        source_stats: Dict[str, int] = {}

        for source, result in zip(sources, source_results):
            if isinstance(result, Exception):
                logger.warning(f"Source {source.name} raised exception: {result!r}")
                source_stats[source.name] = 0
            else:
                count = len(result)
                source_stats[source.name] = count
                all_jobs.extend(result)
                logger.info(f"Source {source.name}: {count} jobs")

        total_found = len(all_jobs)
        logger.info(f"Total raw jobs collected: {total_found}")

        # ------------------------------------------------------------------
        # 6. Basic filtering (before dedup, for speed)
        # ------------------------------------------------------------------
        filtered_jobs = []
        for job in all_jobs:
            passes, reason = passes_basic_filters(job, preferences)
            if passes:
                filtered_jobs.append(job)
            else:
                logger.debug(f"Basic filter rejected: {job.title} @ {job.company} — {reason}")

        logger.info(f"After basic filter: {len(filtered_jobs)} jobs")

        # ------------------------------------------------------------------
        # 7. Deduplicate
        # ------------------------------------------------------------------
        unique_jobs = deduplicate_raw_jobs(filtered_jobs)
        total_unique = len(unique_jobs)
        total_duplicates = len(filtered_jobs) - total_unique
        logger.info(f"After deduplication: {total_unique} unique jobs (removed {total_duplicates})")

        # ------------------------------------------------------------------
        # 8. Filter already-sent jobs
        # ------------------------------------------------------------------
        new_jobs = []
        already_sent_count = 0
        for job in unique_jobs:
            canonical_id = make_canonical_id(
                job.title, job.company,
                job.location or "",
                job.application_url or job.job_url or "",
            )
            if canonical_id in sent_ids:
                already_sent_count += 1
            else:
                new_jobs.append((job, canonical_id))

        logger.info(f"New unseen jobs: {len(new_jobs)} (already sent: {already_sent_count})")

        # ------------------------------------------------------------------
        # 9. Score + match all new jobs
        # ------------------------------------------------------------------
        matched_jobs = []
        rejected_count = 0

        for job, canonical_id in new_jobs:
            try:
                match_result = await self.matcher.match(job, resume_profile, preferences)
                score = match_result["total_score"]

                # Save to DB regardless of score (for tracking)
                db_job = await save_job_to_db(db, job, canonical_id)
                if db_job:
                    await save_match_to_db(db, db_job.id, match_result)

                if score >= min_score:
                    # Build email-ready dict
                    email_job = {
                        **vars(job),
                        **match_result,
                        "id": db_job.id if db_job else None,
                    }
                    matched_jobs.append(email_job)
                    logger.info(f"MATCH [{score}/100]: {job.title} @ {job.company}")
                else:
                    rejected_count += 1
                    logger.debug(f"REJECTED [{score}/100]: {job.title} @ {job.company}")

            except Exception as e:
                logger.warning(f"Error scoring job '{job.title}': {e!r}")

        # Sort by score descending
        matched_jobs.sort(key=lambda j: j["total_score"], reverse=True)

        # ------------------------------------------------------------------
        # 10. Send email
        # ------------------------------------------------------------------
        run_stats = {
            "total_found": total_found,
            "total_unique": total_unique,
            "total_matched": len(matched_jobs),
            "total_rejected": rejected_count,
            "already_sent": already_sent_count,
            "source_stats": {k: v for k, v in source_stats.items() if v > 0},
        }

        emailed_count = 0
        if matched_jobs:
            is_test = not self.settings.is_email_configured
            email_sent = await send_job_email(matched_jobs, run_stats, test_mode=is_test)

            if email_sent:
                emailed_count = len(matched_jobs)
                # Mark each job as sent individually to avoid one bad FK killing the batch
                for email_job in matched_jobs:
                    job_id = email_job.get("id")
                    if not job_id:
                        continue
                    try:
                        sent = SentJob(
                            job_id=job_id,
                            run_id=search_run.id,
                        )
                        db.add(sent)
                        await db.flush()
                    except Exception as e:
                        logger.warning(f"Failed to mark job {job_id} as sent: {e!r}")
                        await db.rollback()

        return {
            "status": "completed",
            "total_found": total_found,
            "total_unique": total_unique,
            "total_matched": len(matched_jobs),
            "total_emailed": emailed_count,
            "total_duplicates": total_duplicates,
            "total_rejected": rejected_count,
            "already_sent": already_sent_count,
            "source_stats": run_stats["source_stats"],
        }
