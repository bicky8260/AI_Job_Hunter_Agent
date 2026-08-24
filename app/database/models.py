"""
SQLAlchemy ORM models for AI Job Hunter.

Tables:
- agent_state    : single-row agent control (enabled/disabled)
- job_preferences: JSON job search preferences
- jobs           : all discovered jobs
- job_matches    : match score + reasoning per job
- sent_jobs      : track which jobs have been emailed
- search_runs    : per-run metadata and statistics
- resume_data    : parsed resume fields
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------

class AgentState(Base):
    """
    Single-row table controlling agent behaviour.
    Always access via AgentState.get_or_create().
    """
    __tablename__ = "agent_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_scheduled_run: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Job (core record)
# ---------------------------------------------------------------------------

class Job(Base):
    """
    A discovered job posting.
    canonical_id is a stable hash used for deduplication.
    """
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    canonical_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Core fields
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Salary
    salary_raw: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    salary_min_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    salary_max_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Experience
    experience_min_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience_max_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience_raw: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Employment
    employment_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Skills (stored as JSON list)
    required_skills: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    preferred_skills: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Content
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Dates
    posted_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    application_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # URLs
    application_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Source metadata
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    source_job_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Extra data as JSON
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Timestamps
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    match: Mapped[Optional["JobMatch"]] = relationship("JobMatch", back_populates="job", uselist=False)
    sent_record: Mapped[Optional["SentJob"]] = relationship("SentJob", back_populates="job", uselist=False)


# ---------------------------------------------------------------------------
# JobMatch — scoring result
# ---------------------------------------------------------------------------

class JobMatch(Base):
    """AI-computed match score and reasoning for a job."""
    __tablename__ = "job_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Scores
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skills_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    experience_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    salary_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Reasoning
    match_reasons: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    gaps: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    match_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    skills_matched: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    skills_missing: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="match")


# ---------------------------------------------------------------------------
# SentJob — deduplication tracker
# ---------------------------------------------------------------------------

class SentJob(Base):
    """Records which jobs have been emailed to prevent re-sending."""
    __tablename__ = "sent_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    email_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Relationship
    job: Mapped["Job"] = relationship("Job", back_populates="sent_record")


# ---------------------------------------------------------------------------
# SearchRun — per-run metadata
# ---------------------------------------------------------------------------

class SearchRun(Base):
    """Tracks each job search run and its results."""
    __tablename__ = "search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    triggered_by: Mapped[str] = mapped_column(
        String(50), nullable=False, default="scheduler"
    )  # "scheduler" | "manual"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="running"
    )  # running | completed | failed | skipped

    # Results
    total_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_emailed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Source breakdown as JSON: {"RemoteOK": 12, "Adzuna": 8, ...}
    source_stats: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# ResumeData — parsed resume
# ---------------------------------------------------------------------------

class ResumeData(Base):
    """Stores parsed resume information for matching."""
    __tablename__ = "resume_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Extracted fields
    skills: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    technologies: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    cloud_platforms: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    devops_tools: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    programming_languages: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    certifications: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    education: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    projects: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    years_of_experience: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Full extracted profile as JSON (for LLM context)
    profile_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
