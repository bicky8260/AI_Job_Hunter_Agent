"""
Naukri.com job source adapter.

IMPORTANT — Integration Status
================================
Naukri.com does NOT provide an authorized public API for third-party
job search integrations. There is no API key program available to
independent developers (only enterprise ATS partnerships via direct
Naukri account management).

This adapter makes honest, best-effort GET requests to Naukri's
public-facing search endpoint using a transparent User-Agent that
identifies this tool. It does NOT:

  - Spoof browser fingerprints (no Sec-Ch-Ua, Sec-Fetch-* headers)
  - Warm up sessions or harvest cookies from the homepage
  - Retry requests that were rejected with a 4xx status code
    (4xx = access denied / bot block — retrying would be evasion)
  - Attempt to bypass CAPTCHA or any anti-bot mechanism

If Naukri blocks the request (returns 4xx), this source returns an
empty list and the agent continues normally using all other sources.

Only transient failures (5xx server errors, network timeouts) are
retried with exponential backoff, which is standard HTTP practice.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.sources.base import JobSource, RawJob

logger = logging.getLogger(__name__)

# Statuses that indicate a transient server-side failure worth retrying.
_TRANSIENT_STATUS_CODES = {500, 502, 503, 504}

# Statuses that mean Naukri has denied access (bot block, bad format, auth required, etc.).
# These are NOT retried — retrying access-denied responses is evasion.
_ACCESS_DENIED_STATUS_CODES = {400, 401, 403, 406, 429}



class NaukriSource(JobSource):
    """
    Best-effort Naukri.com job source.

    See module docstring for important integration notes.

    Behaviour summary:
    - 200 OK  → parse and return jobs
    - 4xx     → log warning, return [] immediately (no retry)
    - 5xx     → retry up to max_retries with exponential backoff
    - Network error → retry up to max_retries with exponential backoff
    - Any unhandled exception → safe_search() catches it and returns []
    """

    name = "Naukri"
    description = "Naukri.com — India's largest job board (best-effort, no authorized API)"
    SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

    # Transparent User-Agent identifying this tool — no browser spoofing.
    _USER_AGENT = "AI-Job-Hunter/1.0 (personal job search tool; not a browser)"

    # Locations recognised by Naukri's search API that overlap with
    # the configured preferences.
    _KNOWN_INDIA_LOCATIONS = {
        "india", "bangalore", "hyderabad", "pune", "mumbai", "chennai",
        "delhi", "gurgaon", "noida", "kolkata",
    }

    def __init__(
        self,
        preferences: Dict[str, Any],
        search_settings: Dict[str, Any],
        max_retries: int = 2,
    ) -> None:
        super().__init__(preferences, search_settings)
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search(self) -> List[RawJob]:
        """
        Search Naukri for jobs matching preferences.
        Returns [] if Naukri is unavailable or blocks the request.
        """
        jobs: List[RawJob] = []
        seen_ids: set = set()

        exp_min = self.preferences.get("experience", {}).get("minimum_years", 1)
        exp_max = self.preferences.get("experience", {}).get("maximum_years", 3)
        queries = self.build_search_queries()[:4]
        search_locations = self._resolve_locations()

        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            follow_redirects=True,
            headers={"User-Agent": self._USER_AGENT},
        ) as client:
            for query in queries:
                for location in search_locations:
                    if len(jobs) >= self.max_jobs:
                        break

                    raw_items = await self._fetch(
                        client, query, location, exp_min, exp_max
                    )

                    for item in raw_items:
                        job_id = str(item.get("jobId", "")).strip()
                        if job_id and job_id in seen_ids:
                            continue
                        if job_id:
                            seen_ids.add(job_id)

                        job = self._parse_job(item)
                        if job:
                            jobs.append(job)

                    # Polite delay between requests.
                    await asyncio.sleep(2.0)

        logger.info(f"Naukri: collected {len(jobs)} jobs")
        return jobs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_locations(self) -> List[str]:
        """
        Return the subset of configured locations that Naukri understands,
        falling back to 'india' if none match.
        """
        pref_locations = [
            loc.lower()
            for loc in self.preferences.get("locations", [])
            if loc.lower() in self._KNOWN_INDIA_LOCATIONS
        ]
        return pref_locations[:3] if pref_locations else ["india"]

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query: str,
        location: str,
        exp_min: float,
        exp_max: float,
    ) -> List[Dict[str, Any]]:
        """
        Fetch one page of Naukri results for a query+location pair.

        - Returns parsed job-detail list on 200.
        - Returns [] immediately on 4xx (access denied / bot block).
        - Retries up to self._max_retries on 5xx or network errors.
        """
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": query,
            "location": location,
            "experience": f"{int(exp_min)},{int(exp_max)}",
            "sort": "1",
            "jobAge": self.max_age_days,
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 2):  # +2 = 1 initial + retries
            try:
                resp = await client.get(self.SEARCH_URL, params=params)

                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("jobDetails", [])
                    logger.info(
                        f"Naukri: '{query}' @ {location} → {len(results)} jobs"
                    )
                    return results

                if resp.status_code in _ACCESS_DENIED_STATUS_CODES:
                    # Access denied — do not retry; that would be evasion.
                    logger.warning(
                        f"Naukri: access denied ({resp.status_code}) for "
                        f"'{query}' @ {location} — skipping (no authorized API available)"
                    )
                    return []

                if resp.status_code in _TRANSIENT_STATUS_CODES:
                    # Server-side transient error — retry is legitimate.
                    logger.warning(
                        f"Naukri: server error {resp.status_code} for "
                        f"'{query}' @ {location} (attempt {attempt}/{self._max_retries + 1})"
                    )
                    last_error = Exception(f"HTTP {resp.status_code}")
                else:
                    # Unknown status — treat as non-retryable.
                    logger.warning(
                        f"Naukri: unexpected status {resp.status_code} for "
                        f"'{query}' @ {location} — skipping"
                    )
                    return []

            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as exc:
                logger.warning(
                    f"Naukri: network error for '{query}' @ {location} "
                    f"(attempt {attempt}/{self._max_retries + 1}): {exc!r}"
                )
                last_error = exc

            # Only sleep between retries, not after the final attempt.
            if attempt <= self._max_retries:
                await asyncio.sleep(2 ** attempt)

        logger.warning(
            f"Naukri: giving up on '{query}' @ {location} after "
            f"{self._max_retries + 1} attempts — last error: {last_error!r}"
        )
        return []

    def _parse_job(self, item: Dict[str, Any]) -> Optional[RawJob]:
        """
        Parse a single Naukri job-detail dict into a RawJob.
        Returns None if required fields are missing.
        """
        title = item.get("title", "").strip()
        company = item.get("companyName", "").strip()
        if not title or not company:
            return None

        placeholders = item.get("placeholders", [])

        salary_text = _extract_placeholder(placeholders, "Salary")
        sal_min, sal_max = _parse_lpa_salary(salary_text)

        exp_text = _extract_placeholder(placeholders, "Experience")
        exp_min_years, exp_max_years = _parse_experience(exp_text)

        # Location: first placeholder that isn't Salary or Experience.
        location = "India"
        for p in placeholders:
            label = p.get("label", "")
            if label and label not in ("Salary", "Experience"):
                location = label
                break

        skills = [
            s.get("label", "")
            for s in item.get("tagsAndSkills", [])
            if s.get("label")
        ]

        return RawJob(
            title=title,
            company=company,
            source=self.name,
            job_url=item.get("jdURL") or None,
            application_url=item.get("jdURL") or None,
            description=item.get("jobDescription") or None,
            location=location,
            salary_raw=salary_text or None,
            salary_min_inr=sal_min,
            salary_max_inr=sal_max,
            salary_currency="INR",
            experience_min_years=exp_min_years,
            experience_max_years=exp_max_years,
            experience_raw=exp_text or None,
            required_skills=skills,
            employment_type="Full-time",
            source_job_id=str(item.get("jobId", "")).strip() or None,
            raw_data=item,
        )


# ---------------------------------------------------------------------------
# Parsing utilities (Naukri-specific)
# ---------------------------------------------------------------------------

def _extract_placeholder(placeholders: List[Dict], label: str) -> str:
    """Return the 'title' value for a named placeholder, or ''."""
    for p in placeholders:
        if p.get("label") == label:
            return p.get("title", "")
    return ""


def _parse_lpa_salary(salary_text: str) -> tuple:
    """
    Parse Indian LPA salary strings like '8-12 Lacs PA', '10 LPA', '₹10-14 LPA'.
    Returns (min_inr, max_inr) in absolute INR (1 Lakh = 100,000 INR).
    """
    if not salary_text:
        return None, None

    numbers = re.findall(r"[\d.]+", salary_text.lower().replace(",", ""))
    lakh = 100_000

    if len(numbers) >= 2:
        try:
            return int(float(numbers[0]) * lakh), int(float(numbers[1]) * lakh)
        except ValueError:
            pass
    elif len(numbers) == 1:
        try:
            return int(float(numbers[0]) * lakh), None
        except ValueError:
            pass

    return None, None


def _parse_experience(exp_text: str) -> tuple:
    """
    Parse experience strings like '1-3 Yrs', '2-5 Years'.
    Returns (min_years, max_years).
    """
    if not exp_text:
        return None, None

    numbers = re.findall(r"[\d.]+", exp_text)
    if len(numbers) >= 2:
        try:
            return float(numbers[0]), float(numbers[1])
        except ValueError:
            pass
    elif len(numbers) == 1:
        try:
            return float(numbers[0]), None
        except ValueError:
            pass

    return None, None
