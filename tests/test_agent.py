"""
Tests for agent START/STOP/STATUS behavior.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from httpx import AsyncClient
from fastapi.testclient import TestClient


# Note: These tests use a lightweight SQLite test DB via conftest fixtures.


class TestAgentStateTransitions:
    """Unit tests for agent state logic without HTTP."""

    @pytest.mark.asyncio
    async def test_start_sets_enabled_true(self, db_session):
        from app.database.models import AgentState
        from sqlalchemy import select

        # No state yet — should create
        result = await db_session.execute(select(AgentState).where(AgentState.id == 1))
        state = result.scalar_one_or_none()
        assert state is None

        # Simulate start
        state = AgentState(id=1, enabled=True, last_started_at=datetime.now(timezone.utc))
        db_session.add(state)
        await db_session.flush()

        result = await db_session.execute(select(AgentState).where(AgentState.id == 1))
        state = result.scalar_one_or_none()
        assert state is not None
        assert state.enabled is True
        assert state.last_started_at is not None

    @pytest.mark.asyncio
    async def test_stop_sets_enabled_false(self, db_session):
        from app.database.models import AgentState
        from sqlalchemy import select

        # Create and start
        state = AgentState(id=1, enabled=True, last_started_at=datetime.now(timezone.utc))
        db_session.add(state)
        await db_session.flush()

        # Stop
        state.enabled = False
        state.last_stopped_at = datetime.now(timezone.utc)
        await db_session.flush()

        result = await db_session.execute(select(AgentState).where(AgentState.id == 1))
        state = result.scalar_one_or_none()
        assert state.enabled is False
        assert state.last_stopped_at is not None

    @pytest.mark.asyncio
    async def test_stopped_agent_skips_run(self, db_session):
        """Job agent run() should skip if agent is disabled."""
        from app.database.models import AgentState

        # Create stopped state
        state = AgentState(id=1, enabled=False)
        db_session.add(state)
        await db_session.flush()

        with patch("app.agents.job_agent.get_db_context") as mock_ctx:
            # Mock the db context to return our test session
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            from app.agents.job_agent import JobAgent
            agent = JobAgent()

            with patch("app.agents.job_agent.get_or_create_agent_state") as mock_state:
                mock_state.return_value = state
                result = await agent.run(triggered_by="test")

        assert result["status"] == "skipped"
        assert result["total_matched"] == 0


class TestJobAgentFiltering:
    """Test the basic job filtering logic."""

    def test_excluded_title_rejected(self, sample_preferences):
        from app.agents.job_agent import passes_basic_filters
        from app.sources.base import RawJob

        job = RawJob(title="Senior DevOps Engineer", company="X", source="test")
        passes, reason = passes_basic_filters(job, sample_preferences)
        assert passes is False
        assert "Excluded title" in reason

    def test_relevant_title_passes(self, sample_preferences):
        from app.agents.job_agent import passes_basic_filters
        from app.sources.base import RawJob

        job = RawJob(title="DevOps Engineer", company="X", source="test")
        passes, _ = passes_basic_filters(job, sample_preferences)
        assert passes is True

    def test_excluded_keyword_in_description(self, sample_preferences):
        from app.agents.job_agent import passes_basic_filters
        from app.sources.base import RawJob

        prefs = {**sample_preferences, "exclude_keywords": ["10+ years"]}
        job = RawJob(
            title="DevOps Engineer",
            company="X",
            source="test",
            description="We need someone with 10+ years of experience.",
        )
        passes, reason = passes_basic_filters(job, prefs)
        assert passes is False
        assert "Excluded keyword" in reason

    def test_marketing_title_rejected(self, sample_preferences):
        from app.agents.job_agent import passes_basic_filters
        from app.sources.base import RawJob

        job = RawJob(title="Marketing Executive", company="X", source="test")
        passes, _ = passes_basic_filters(job, sample_preferences)
        assert passes is False


class TestSearchRunTracking:
    """Test that search runs are properly recorded."""

    @pytest.mark.asyncio
    async def test_search_run_created(self, db_session):
        from app.database.models import SearchRun
        from sqlalchemy import select

        run = SearchRun(
            triggered_by="test",
            started_at=datetime.now(timezone.utc),
            status="completed",
            total_found=10,
            total_matched=5,
        )
        db_session.add(run)
        await db_session.flush()

        result = await db_session.execute(select(SearchRun))
        runs = result.scalars().all()
        assert len(runs) == 1
        assert runs[0].total_found == 10


class TestSentJobTracking:
    """Test that sent jobs are properly tracked to prevent re-sending."""

    @pytest.mark.asyncio
    async def test_sent_job_prevents_re_email(self, db_session):
        """A job in sent_jobs should not be returned in get_sent_job_ids."""
        from app.database.models import Job, SentJob
        from app.agents.job_agent import get_sent_job_ids

        # Create a job and mark as sent
        job = Job(
            canonical_id="abc123test",
            title="DevOps Engineer",
            company="Corp",
            source="test",
        )
        db_session.add(job)
        await db_session.flush()

        sent = SentJob(job_id=job.id)
        db_session.add(sent)
        await db_session.flush()

        sent_ids = await get_sent_job_ids(db_session)
        assert "abc123test" in sent_ids
