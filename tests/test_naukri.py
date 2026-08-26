import asyncio
from unittest.mock import patch, AsyncMock
import pytest
import respx
import httpx

from app.sources.naukri import NaukriSource, _parse_lpa_salary, _parse_experience


# ---------------------------------------------------------------------------
# Speed up tests by patching asyncio.sleep globally (no real waiting).
# The sleep calls are still exercised — they just return immediately.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Replace asyncio.sleep with an instant no-op for all tests in this module."""
    async def _instant_sleep(_):
        pass
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)




# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PREFERENCES = {
    "job_titles": ["DevOps Engineer", "SRE"],
    "locations": ["India", "Bangalore"],
    "experience": {"minimum_years": 1, "maximum_years": 3},
}

SEARCH_SETTINGS = {
    "max_jobs_per_source": 50,
    "request_timeout_seconds": 10,
    "max_job_age_days": 7,
}

NAUKRI_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"


def make_source(**kwargs) -> NaukriSource:
    return NaukriSource(PREFERENCES, SEARCH_SETTINGS, **kwargs)


def make_job_item(
    job_id="JOB001",
    title="DevOps Engineer",
    company="Tech Corp",
    jd_url="https://www.naukri.com/job-listings/devops-engineer-tech-corp-1",
    salary="10-14 Lacs PA",
    experience="1-3 Yrs",
    location_label="Bangalore",
    skills=("Kubernetes", "Terraform"),
    description="Great DevOps role.",
) -> dict:
    return {
        "jobId": job_id,
        "title": title,
        "companyName": company,
        "jdURL": jd_url,
        "jobDescription": description,
        "placeholders": [
            {"label": location_label, "title": location_label},
            {"label": "Experience", "title": experience},
            {"label": "Salary", "title": salary},
        ],
        "tagsAndSkills": [{"label": s} for s in skills],
    }


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestNaukriSearch:

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_jobs_on_200(self):
        """200 response with jobDetails → correctly populated RawJob list."""
        payload = {"jobDetails": [make_job_item()]}
        respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

        source = make_source(max_retries=0)
        jobs = await source.search()

        assert len(jobs) >= 1
        job = jobs[0]
        assert job.title == "DevOps Engineer"
        assert job.company == "Tech Corp"
        assert job.source == "Naukri"
        assert job.salary_currency == "INR"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_deduplicates_by_job_id(self):
        """Same jobId returned by two queries must appear only once."""
        item = make_job_item(job_id="DUP01")
        payload = {"jobDetails": [item]}
        respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))

        source = make_source(max_retries=0)
        jobs = await source.search()

        ids = [j.source_job_id for j in jobs]
        assert ids.count("DUP01") == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_respects_max_jobs(self):
        """
        Source stops issuing new fetches once max_jobs_per_source is reached.
        Note: it does not truncate mid-batch; it stops before the *next* fetch.
        With 2 queries and max_jobs=3, only the first query fires.
        The second query is skipped because len(jobs) >= max_jobs after the first batch.
        """
        first_batch = [make_job_item(job_id=f"A{i}", title=f"First {i}") for i in range(5)]
        second_batch = [make_job_item(job_id=f"B{i}", title=f"Second {i}") for i in range(5)]

        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            batch = first_batch if call_count == 1 else second_batch
            return httpx.Response(200, json={"jobDetails": batch})

        respx.get(NAUKRI_SEARCH_URL).mock(side_effect=handler)

        # 2 queries, 1 location, max_jobs=3 → first fetch returns 5 jobs.
        # After first fetch len(jobs)=5 >= max_jobs=3 → second query skipped.
        prefs = {
            **PREFERENCES,
            "job_titles": ["DevOps Engineer", "SRE"],
            "locations": ["India"],
        }
        settings = {**SEARCH_SETTINGS, "max_jobs_per_source": 3}
        source = NaukriSource(prefs, settings, max_retries=0)
        jobs = await source.search()

        # Only 1 batch fetched (the second query was skipped).
        assert call_count == 1
        # All items from the first batch are returned (no mid-batch truncation).
        assert len(jobs) == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_empty_list_when_no_jobs(self):
        """200 response with empty jobDetails → returns []."""
        respx.get(NAUKRI_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"jobDetails": []})
        )
        source = make_source(max_retries=0)
        jobs = await source.search()
        assert jobs == []


# ---------------------------------------------------------------------------
# _parse_job tests
# ---------------------------------------------------------------------------

class TestParseJob:

    def test_extracts_title_and_company(self):
        source = make_source()
        job = source._parse_job(make_job_item(title="SRE", company="Infra Co"))
        assert job.title == "SRE"
        assert job.company == "Infra Co"

    def test_extracts_salary_in_inr(self):
        source = make_source()
        job = source._parse_job(make_job_item(salary="10-14 Lacs PA"))
        assert job.salary_min_inr == 1_000_000
        assert job.salary_max_inr == 1_400_000
        assert job.salary_currency == "INR"

    def test_extracts_experience(self):
        source = make_source()
        job = source._parse_job(make_job_item(experience="1-3 Yrs"))
        assert job.experience_min_years == 1.0
        assert job.experience_max_years == 3.0

    def test_extracts_skills(self):
        source = make_source()
        job = source._parse_job(make_job_item(skills=("Kubernetes", "GCP", "Terraform")))
        assert "Kubernetes" in job.required_skills
        assert "GCP" in job.required_skills

    def test_extracts_location_from_placeholder(self):
        source = make_source()
        job = source._parse_job(make_job_item(location_label="Hyderabad"))
        assert job.location == "Hyderabad"

    def test_extracts_job_url(self):
        source = make_source()
        url = "https://www.naukri.com/job-listings/devops-1"
        job = source._parse_job(make_job_item(jd_url=url))
        assert job.job_url == url
        assert job.application_url == url

    def test_returns_none_when_title_missing(self):
        source = make_source()
        item = make_job_item()
        item["title"] = ""
        assert source._parse_job(item) is None

    def test_returns_none_when_company_missing(self):
        source = make_source()
        item = make_job_item()
        item["companyName"] = ""
        assert source._parse_job(item) is None

    def test_handles_missing_optional_fields(self):
        """Minimal item with only required fields should parse without error."""
        source = make_source()
        item = {"jobId": "X1", "title": "DevOps Engineer", "companyName": "Acme"}
        job = source._parse_job(item)
        assert job is not None
        assert job.title == "DevOps Engineer"
        assert job.salary_min_inr is None
        assert job.experience_min_years is None
        assert job.required_skills == []


# ---------------------------------------------------------------------------
# Access-denied (4xx) — must NOT retry
# ---------------------------------------------------------------------------

class TestAccessDeniedBehaviour:

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_on_403(self):
        """403 Forbidden → return [] immediately, do not retry."""
        route = respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(403))

        source = make_source(max_retries=2)
        jobs = await source.search()

        assert jobs == []
        # Each query×location fires at most one request — never retried.
        assert route.call_count <= len(source.build_search_queries()) * len(
            source._resolve_locations()
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_on_406(self):
        """406 Not Acceptable (Naukri bot block) → return [] immediately."""
        respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(406))
        source = make_source(max_retries=2)
        jobs = await source.search()
        assert jobs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_on_401(self):
        """401 Unauthorized → return [] immediately."""
        respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(401))
        source = make_source(max_retries=2)
        jobs = await source.search()
        assert jobs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_403_does_not_retry(self):
        """Confirm 403 results in exactly 1 attempt per query (no backoff retries)."""
        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(403)

        respx.get(NAUKRI_SEARCH_URL).mock(side_effect=handler)

        prefs = {**PREFERENCES, "job_titles": ["DevOps Engineer"]}
        prefs["locations"] = ["India"]  # 1 location
        source = NaukriSource(prefs, SEARCH_SETTINGS, max_retries=3)
        await source.search()

        # 1 query × 1 location = 1 attempt total (no retries on 4xx)
        assert call_count == 1


# ---------------------------------------------------------------------------
# Transient failures (5xx, network) — legitimate retry
# ---------------------------------------------------------------------------

class TestTransientRetryBehaviour:

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_500_then_succeeds(self):
        """500 on first attempt → retries → 200 on second → returns jobs."""
        payload = {"jobDetails": [make_job_item()]}
        respx.get(NAUKRI_SEARCH_URL).mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, json=payload),
            ]
        )

        prefs = {**PREFERENCES, "job_titles": ["DevOps Engineer"], "locations": ["India"]}
        source = NaukriSource(prefs, SEARCH_SETTINGS, max_retries=1)
        jobs = await source.search()

        assert len(jobs) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_after_all_500_retries_exhausted(self):
        """All attempts return 500 → source returns []."""
        respx.get(NAUKRI_SEARCH_URL).mock(return_value=httpx.Response(500))

        prefs = {**PREFERENCES, "job_titles": ["DevOps Engineer"], "locations": ["India"]}
        source = NaukriSource(prefs, SEARCH_SETTINGS, max_retries=1)
        jobs = await source.search()

        assert jobs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_connection_error(self):
        """Network error → retries → eventually returns []."""
        respx.get(NAUKRI_SEARCH_URL).mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        prefs = {**PREFERENCES, "job_titles": ["SRE"], "locations": ["India"]}
        source = NaukriSource(prefs, SEARCH_SETTINGS, max_retries=1)
        jobs = await source.search()

        assert jobs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_safe_search_never_raises(self):
        """Any exception in search() must be caught by safe_search()."""
        respx.get(NAUKRI_SEARCH_URL).mock(side_effect=RuntimeError("Unexpected!"))

        source = make_source(max_retries=0)
        result = await source.safe_search()

        assert result == []


# ---------------------------------------------------------------------------
# Ethical compliance — no browser fingerprinting
# ---------------------------------------------------------------------------

class TestEthicalCompliance:

    @pytest.mark.asyncio
    @respx.mock
    async def test_user_agent_is_not_browser_spoof(self):
        """User-Agent must NOT contain browser fingerprint strings."""
        captured_headers = {}

        async def capture(request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={"jobDetails": []})

        respx.get(NAUKRI_SEARCH_URL).mock(side_effect=capture)

        source = make_source(max_retries=0)
        await source.search()

        ua = captured_headers.get("user-agent", "")
        # Must not impersonate a browser
        assert "Mozilla" not in ua, f"User-Agent spoofs Mozilla: {ua}"
        assert "Chrome" not in ua, f"User-Agent spoofs Chrome: {ua}"
        assert "AppleWebKit" not in ua, f"User-Agent spoofs WebKit: {ua}"
        assert "Safari" not in ua, f"User-Agent spoofs Safari: {ua}"

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_bot_evasion_headers_sent(self):
        """Requests must NOT include bot-evasion or browser-fingerprint headers."""
        captured_headers = {}

        async def capture(request):
            captured_headers.update({k.lower(): v for k, v in request.headers.items()})
            return httpx.Response(200, json={"jobDetails": []})

        respx.get(NAUKRI_SEARCH_URL).mock(side_effect=capture)

        source = make_source(max_retries=0)
        await source.search()

        forbidden_headers = [
            "clientid",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
            "cookie",
            "origin",
        ]
        for header in forbidden_headers:
            assert header not in captured_headers, (
                f"Forbidden bot-evasion header '{header}' was sent in request"
            )


# ---------------------------------------------------------------------------
# Parsing utility tests (re-validated here for naukri module's own copies)
# ---------------------------------------------------------------------------

class TestParsingUtilities:

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

    def test_parse_lpa_empty(self):
        assert _parse_lpa_salary("") == (None, None)
        assert _parse_lpa_salary(None) == (None, None)

    def test_parse_experience_range(self):
        assert _parse_experience("1-3 Yrs") == (1.0, 3.0)
        assert _parse_experience("2-5 Years") == (2.0, 5.0)

    def test_parse_experience_empty(self):
        assert _parse_experience("") == (None, None)
        assert _parse_experience(None) == (None, None)
