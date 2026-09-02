"""
Job board adapters:
- RemoteOK (public JSON API, no auth)
- Arbeitnow (public JSON feed, no auth)
- Adzuna (REST API, free key required)
- Jooble (REST API, free key required)
- The Muse (public API, no auth)
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.sources.base import JobSource, RawJob

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RemoteOK
# ---------------------------------------------------------------------------

class RemoteOKSource(JobSource):
    """
    Fetches remote jobs from RemoteOK public API.
    No authentication required. Great for remote DevOps/SRE roles.
    API: https://remoteok.com/api
    """

    name = "RemoteOK"
    description = "RemoteOK public job board (remote tech jobs)"
    BASE_URL = "https://remoteok.com/api"
    DEVOPS_TAGS = ["devops", "sre", "cloud", "kubernetes", "terraform", "platform", "infrastructure"]

    async def search(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
                resp = await client.get(
                    self.BASE_URL,
                    headers={"User-Agent": "AI-Job-Hunter/1.0 (personal job search tool)"},
                )
                resp.raise_for_status()
                data = resp.json()

            cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("legal"):  # skip the legal notice item
                    continue

                # Filter by relevant tags
                tags = [t.lower() for t in item.get("tags", [])]
                if not any(t in tags for t in self.DEVOPS_TAGS):
                    continue

                # Parse date
                posted = None
                date_str = item.get("date", "")
                if date_str:
                    try:
                        posted = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if posted < cutoff:
                            continue  # too old
                    except (ValueError, AttributeError):
                        pass

                # Extract salary
                salary_raw = item.get("salary", "") or ""
                sal_min, sal_max = _parse_usd_salary_range(salary_raw)

                job = RawJob(
                    title=item.get("position", "Unknown Title"),
                    company=item.get("company", "Unknown Company"),
                    source=self.name,
                    job_url=item.get("url", ""),
                    application_url=item.get("apply_url", "") or item.get("url", ""),
                    description=item.get("description", ""),
                    location=item.get("location", "Remote") or "Remote",
                    work_mode="Remote",
                    salary_raw=salary_raw or None,
                    salary_min_inr=_usd_to_inr(sal_min) if sal_min else None,
                    salary_max_inr=_usd_to_inr(sal_max) if sal_max else None,
                    salary_currency="USD" if salary_raw else None,
                    required_skills=tags,
                    posted_date=posted,
                    source_job_id=str(item.get("id", "")),
                    raw_data=item,
                )
                jobs.append(job)

                if len(jobs) >= self.max_jobs:
                    break

        except Exception as e:
            logger.warning(f"RemoteOK error: {e!r}")

        return jobs


# ---------------------------------------------------------------------------
# Arbeitnow
# ---------------------------------------------------------------------------

class ArbeitnowSource(JobSource):
    """
    Fetches jobs from Arbeitnow public JSON feed.
    Specializes in remote-friendly tech jobs. No auth required.
    API: https://www.arbeitnow.com/api/job-board-api
    """

    name = "Arbeitnow"
    description = "Arbeitnow remote job board (Europe/global tech)"
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
    RELEVANT_TAGS = ["devops", "cloud", "sre", "platform", "infrastructure", "kubernetes", "terraform"]

    async def search(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
                for page in range(1, 4):  # fetch up to 3 pages
                    resp = await client.get(
                        self.BASE_URL,
                        params={"page": page},
                        headers={"User-Agent": "AI-Job-Hunter/1.0"},
                    )
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    items = data.get("data", [])
                    if not items:
                        break

                    for item in items:
                        tags = [t.lower() for t in item.get("tags", [])]
                        title_lower = item.get("title", "").lower()

                        # Check relevance
                        relevant = any(t in tags for t in self.RELEVANT_TAGS) or any(
                            t in title_lower for t in self.RELEVANT_TAGS
                        )
                        if not relevant:
                            continue

                        # Parse date
                        posted = None
                        created_at = item.get("created_at")
                        if created_at:
                            try:
                                posted = datetime.fromtimestamp(created_at, tz=timezone.utc)
                            except (ValueError, TypeError):
                                pass

                        job = RawJob(
                            title=item.get("title", ""),
                            company=item.get("company_name", ""),
                            source=self.name,
                            job_url=item.get("url", ""),
                            application_url=item.get("url", ""),
                            description=item.get("description", ""),
                            location=item.get("location", "Remote"),
                            work_mode="Remote" if item.get("remote", False) else "Hybrid",
                            required_skills=tags,
                            posted_date=posted,
                            source_job_id=item.get("slug", ""),
                            raw_data=item,
                        )
                        jobs.append(job)

                        if len(jobs) >= self.max_jobs:
                            return jobs

                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"Arbeitnow error: {e!r}")

        return jobs


# ---------------------------------------------------------------------------
# Adzuna
# ---------------------------------------------------------------------------

class AdzunaSource(JobSource):
    """
    Adzuna job search API. Requires free API key.
    Excellent India coverage.
    Sign up: https://developer.adzuna.com/
    """

    name = "Adzuna"
    description = "Adzuna job search API (India DevOps jobs)"
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self, preferences: Dict[str, Any], search_settings: Dict[str, Any]):
        super().__init__(preferences, search_settings)
        settings = get_settings()
        self.app_id = settings.adzuna_app_id
        self.app_key = settings.adzuna_app_key

    async def search(self) -> List[RawJob]:
        if not self.app_id or not self.app_key:
            logger.info("Adzuna: no API keys configured — skipping")
            return []

        jobs: List[RawJob] = []
        queries = self.build_search_queries()
        countries = self.search_settings.get("country_codes", ["in"])

        async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
            for country in countries[:1]:  # prioritize India
                for query in queries[:3]:
                    try:
                        resp = await client.get(
                            f"{self.BASE_URL}/{country}/search/1",
                            params={
                                "app_id": self.app_id,
                                "app_key": self.app_key,
                                "what": query,
                                "where": "India",
                                "results_per_page": 20,
                                "max_days_old": self.max_age_days,
                                "sort_by": "date",
                                "full_time": 1,
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()

                        for item in data.get("results", []):
                            posted = None
                            created = item.get("created", "")
                            if created:
                                try:
                                    posted = datetime.fromisoformat(created.replace("Z", "+00:00"))
                                except (ValueError, AttributeError):
                                    pass

                            # Parse salary from Adzuna
                            sal_min = item.get("salary_min")
                            sal_max = item.get("salary_max")
                            currency = item.get("salary_currency_code", "INR")

                            job = RawJob(
                                title=item.get("title", ""),
                                company=item.get("company", {}).get("display_name", ""),
                                source=self.name,
                                job_url=item.get("redirect_url", ""),
                                application_url=item.get("redirect_url", ""),
                                description=item.get("description", ""),
                                location=item.get("location", {}).get("display_name", "India"),
                                salary_min_inr=int(sal_min) if sal_min and currency == "INR" else None,
                                salary_max_inr=int(sal_max) if sal_max and currency == "INR" else None,
                                salary_currency=currency,
                                posted_date=posted,
                                source_job_id=item.get("id", ""),
                                raw_data=item,
                            )
                            jobs.append(job)

                        await asyncio.sleep(1)  # be polite to API

                    except Exception as e:
                        logger.warning(f"Adzuna search error for query '{query}': {e!r}")

                    if len(jobs) >= self.max_jobs:
                        return jobs

        return jobs


# ---------------------------------------------------------------------------
# Jooble
# ---------------------------------------------------------------------------

class JoobleSource(JobSource):
    """
    Jooble job aggregator API. Requires free API key.
    Good India coverage for DevOps roles.
    Sign up: https://jooble.org/api/about
    """

    name = "Jooble"
    description = "Jooble job aggregator API"
    BASE_URL = "https://jooble.org/api"

    def __init__(self, preferences: Dict[str, Any], search_settings: Dict[str, Any]):
        super().__init__(preferences, search_settings)
        self.api_key = get_settings().jooble_api_key

    async def search(self) -> List[RawJob]:
        if not self.api_key:
            logger.info("Jooble: no API key configured — skipping")
            return []

        jobs: List[RawJob] = []
        queries = self.build_search_queries()

        async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
            for query in queries[:3]:
                try:
                    resp = await client.post(
                        f"{self.BASE_URL}/{self.api_key}",
                        json={
                            "keywords": query,
                            "location": "India",
                            "resultonpage": 20,
                            "page": 1,
                        },
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for item in data.get("jobs", []):
                        salary_raw = item.get("salary", "")
                        posted = None
                        date_str = item.get("updated", "")
                        if date_str:
                            try:
                                posted = datetime.fromisoformat(date_str[:19])
                            except (ValueError, AttributeError):
                                pass

                        job = RawJob(
                            title=item.get("title", ""),
                            company=item.get("company", ""),
                            source=self.name,
                            job_url=item.get("link", ""),
                            application_url=item.get("link", ""),
                            description=item.get("snippet", ""),
                            location=item.get("location", "India"),
                            salary_raw=salary_raw or None,
                            posted_date=posted,
                            source_job_id=item.get("id", ""),
                            raw_data=item,
                        )
                        jobs.append(job)

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.warning(f"Jooble search error for '{query}': {e!r}")

                if len(jobs) >= self.max_jobs:
                    break

        return jobs


# ---------------------------------------------------------------------------
# The Muse
# ---------------------------------------------------------------------------

class TheMuseSource(JobSource):
    """
    The Muse public job API. No authentication required.
    Tech company focus. Good for startup and mid-size DevOps roles.
    API: https://www.themuse.com/developers/api/v2
    """

    name = "TheMuse"
    description = "The Muse public job API (tech companies)"
    BASE_URL = "https://www.themuse.com/api/public/jobs"
    RELEVANT_CATEGORIES = ["Engineering", "IT", "DevOps", "Cloud", "Infrastructure"]

    async def search(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
                for page in range(1, 4):
                    resp = await client.get(
                        self.BASE_URL,
                        params={
                            "category": "Engineering",
                            "level": "Mid Level,Entry Level",
                            "page": page,
                        },
                    )
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break

                    for item in results:
                        title = item.get("name", "")
                        title_lower = title.lower()

                        # Filter for relevant roles
                        relevant_terms = ["devops", "sre", "cloud", "platform", "infrastructure", "reliability"]
                        if not any(t in title_lower for t in relevant_terms):
                            continue

                        # Extract location
                        locations = item.get("locations", [{}])
                        loc_name = locations[0].get("name", "") if locations else ""
                        is_remote = any("remote" in l.get("name", "").lower() for l in locations)

                        job = RawJob(
                            title=title,
                            company=item.get("company", {}).get("name", ""),
                            source=self.name,
                            job_url=item.get("refs", {}).get("landing_page", ""),
                            application_url=item.get("refs", {}).get("landing_page", ""),
                            description=item.get("contents", ""),
                            location=loc_name or "Not specified",
                            work_mode="Remote" if is_remote else None,
                            source_job_id=str(item.get("id", "")),
                            raw_data=item,
                        )
                        jobs.append(job)

                    await asyncio.sleep(0.5)

                    if len(jobs) >= self.max_jobs:
                        break

        except Exception as e:
            logger.warning(f"TheMuse error: {e!r}")

        return jobs


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _parse_usd_salary_range(salary_str: str) -> tuple:
    """Parse a USD salary string like '$80k - $120k' → (80000, 120000)."""
    if not salary_str:
        return None, None
    numbers = re.findall(r"[\d,]+(?:\.\d+)?k?", salary_str.lower())
    parsed = []
    for n in numbers:
        n = n.replace(",", "")
        if n.endswith("k"):
            parsed.append(float(n[:-1]) * 1000)
        else:
            try:
                parsed.append(float(n))
            except ValueError:
                pass
    if len(parsed) >= 2:
        return int(parsed[0]), int(parsed[1])
    elif len(parsed) == 1:
        return int(parsed[0]), None
    return None, None


def _usd_to_inr(usd_amount: Optional[int]) -> Optional[int]:
    """Convert USD to INR at a fixed approximate rate."""
    if usd_amount is None:
        return None
    USD_TO_INR = 83  # approximate rate
    return int(usd_amount * USD_TO_INR)
