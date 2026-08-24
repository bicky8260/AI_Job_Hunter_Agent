"""
Tests for job source adapters.
All external HTTP calls are mocked — no real API calls.
"""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx

from app.sources.base import RawJob
from app.sources.job_boards import RemoteOKSource, ArbeitnowSource
from app.sources.company_careers import _parse_lpa_salary, _parse_experience, NaukriSource


SAMPLE_PREFERENCES = {
    "job_titles": ["DevOps Engineer", "SRE"],
    "locations": ["India", "Remote"],
    "work_mode": ["Remote"],
    "experience": {"minimum_years": 1, "maximum_years": 3},
}

SAMPLE_SEARCH_SETTINGS = {
    "max_jobs_per_source": 50,
    "request_timeout_seconds": 10,
    "max_job_age_days": 7,
    "country_codes": ["in"],
}


# ─── RemoteOK ─────────────────────────────────────────────────────────────────

class TestRemoteOKSource:

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_devops_jobs(self):
        """RemoteOK returns jobs with relevant tags."""
        mock_data = [
            {"legal": True},  # Skip this
            {
                "id": 1001,
                "position": "DevOps Engineer",
                "company": "Remote Tech",
                "tags": ["devops", "kubernetes", "terraform"],
                "location": "Remote",
                "url": "https://remoteok.com/jobs/1001",
                "apply_url": "https://remoteok.com/apply/1001",
                "description": "<p>We need a DevOps Engineer with K8s experience</p>",
                "date": "2026-08-20T00:00:00Z",
            },
            {
                "id": 1002,
                "position": "Marketing Manager",
                "company": "Corp",
                "tags": ["marketing"],
                "location": "Remote",
                "url": "https://remoteok.com/jobs/1002",
                "date": "2026-08-20T00:00:00Z",
            },
        ]

        respx.get("https://remoteok.com/api").mock(
            return_value=httpx.Response(200, json=mock_data)
        )

        source = RemoteOKSource(SAMPLE_PREFERENCES, SAMPLE_SEARCH_SETTINGS)
        jobs = await source.search()

        # Should find the DevOps job but not the marketing one
        assert len(jobs) == 1
        assert jobs[0].title == "DevOps Engineer"
        assert jobs[0].company == "Remote Tech"
        assert "kubernetes" in jobs[0].required_skills

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_handles_network_error_gracefully(self):
        """RemoteOK should return [] if request fails."""
        respx.get("https://remoteok.com/api").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        source = RemoteOKSource(SAMPLE_PREFERENCES, SAMPLE_SEARCH_SETTINGS)
        jobs = await source.safe_search()  # safe_search wraps and catches
        assert jobs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_handles_server_error(self):
        """RemoteOK should return [] on 500 error."""
        respx.get("https://remoteok.com/api").mock(
            return_value=httpx.Response(500)
        )
        source = RemoteOKSource(SAMPLE_PREFERENCES, SAMPLE_SEARCH_SETTINGS)
        jobs = await source.safe_search()
        assert jobs == []


# ─── Salary and experience parsing ───────────────────────────────────────────

class TestSalaryParsing:

    def test_parse_lpa_range(self):
        min_inr, max_inr = _parse_lpa_salary("8-12 Lacs PA")
        assert min_inr == 800_000
        assert max_inr == 1_200_000

    def test_parse_lpa_single(self):
        min_inr, max_inr = _parse_lpa_salary("10 LPA")
        assert min_inr == 1_000_000
        assert max_inr is None

    def test_parse_lpa_rupee_symbol(self):
        min_inr, max_inr = _parse_lpa_salary("₹10-14 LPA")
        assert min_inr == 1_000_000
        assert max_inr == 1_400_000

    def test_parse_empty_salary(self):
        min_inr, max_inr = _parse_lpa_salary("")
        assert min_inr is None
        assert max_inr is None

    def test_parse_none_salary(self):
        min_inr, max_inr = _parse_lpa_salary(None)
        assert min_inr is None
        assert max_inr is None


class TestExperienceParsing:

    def test_parse_years_range(self):
        min_y, max_y = _parse_experience("1-3 Yrs")
        assert min_y == 1.0
        assert max_y == 3.0

    def test_parse_years_text(self):
        min_y, max_y = _parse_experience("2-5 Years")
        assert min_y == 2.0
        assert max_y == 5.0

    def test_parse_empty(self):
        min_y, max_y = _parse_experience("")
        assert min_y is None
        assert max_y is None


# ─── Source base class ────────────────────────────────────────────────────────

class TestJobSourceBase:

    def test_safe_search_catches_exception(self):
        """safe_search should never raise."""
        import asyncio
        from app.sources.base import JobSource

        class BrokenSource(JobSource):
            name = "BrokenSource"
            async def search(self):
                raise RuntimeError("Intentional test failure")

        source = BrokenSource(SAMPLE_PREFERENCES, SAMPLE_SEARCH_SETTINGS)
        # Should not raise
        result = asyncio.run(source.safe_search())
        assert result == []

    def test_raw_job_repr(self):
        job = RawJob(title="DevOps Engineer", company="Test Corp", source="TestSource")
        assert "DevOps Engineer" in repr(job)
        assert "Test Corp" in repr(job)
