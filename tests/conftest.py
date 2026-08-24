"""
Test configuration and shared fixtures.
"""
import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.database import Base


# ─── Test database ───────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a test database engine with SQLite."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ─── Sample data ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_job():
    """A sample RawJob for testing."""
    from app.sources.base import RawJob
    return RawJob(
        title="DevOps Engineer",
        company="Tech Corp",
        source="TestSource",
        location="Remote India",
        work_mode="Remote",
        description=(
            "We are looking for a DevOps Engineer with experience in "
            "Kubernetes, GCP, Terraform, Docker, and GitLab CI/CD. "
            "Experience with Helm and ArgoCD is a plus. "
            "1-3 years of experience required. Remote India. "
            "Salary: 10-14 LPA."
        ),
        salary_raw="₹10-14 LPA",
        salary_min_inr=1_000_000,
        salary_max_inr=1_400_000,
        experience_min_years=1.0,
        experience_max_years=3.0,
        experience_raw="1-3 years",
        required_skills=["Kubernetes", "GCP", "Terraform", "Docker", "GitLab CI/CD"],
        employment_type="Full-time",
        application_url="https://example.com/apply/devops-engineer",
        job_url="https://example.com/jobs/devops-engineer-123",
    )


@pytest.fixture
def sample_resume_profile():
    """A sample parsed resume profile."""
    return {
        "all_skills_flat": [
            "gcp", "google cloud", "gke", "kubernetes", "k8s",
            "docker", "terraform", "helm", "argocd", "argo cd",
            "jenkins", "gitlab ci/cd", "python", "bash", "linux",
            "prometheus", "grafana", "git", "ci/cd",
        ],
        "skills": ["kubernetes", "docker", "terraform", "gcp"],
        "technologies": ["Kubernetes", "Docker", "Terraform", "GCP"],
        "cloud_platforms": ["gcp", "google cloud", "gke"],
        "devops_tools": ["docker", "kubernetes", "terraform", "helm", "argocd", "jenkins"],
        "programming_languages": ["python", "bash"],
        "certifications": [],
        "years_of_experience": 2.0,
    }


@pytest.fixture
def sample_preferences():
    """Sample job preferences for testing."""
    return {
        "job_titles": ["DevOps Engineer", "SRE", "Cloud Engineer", "Platform Engineer"],
        "locations": ["India", "Remote India", "Remote"],
        "work_mode": ["Remote", "Work From Home", "Hybrid"],
        "minimum_salary_inr": 1_000_000,
        "employment_types": ["Full-time"],
        "preferred_skills": ["GCP", "Kubernetes", "Terraform", "Docker", "GitLab CI/CD"],
        "exclude_titles": ["Senior DevOps Engineer", "Lead DevOps Engineer", "Director", "Manager"],
        "exclude_keywords": [],
        "experience": {"minimum_years": 1, "maximum_years": 3},
    }
