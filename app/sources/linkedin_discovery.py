"""
LinkedIn URL Discovery Source.

IMPORTANT: This source does NOT scrape LinkedIn, log into LinkedIn,
use LinkedIn cookies, or bypass any access controls.

Instead, it uses SerpAPI (a legal Google Search API) to query:
  site:linkedin.com/jobs/view <job title> India

This returns LinkedIn job URLs from Google's public search index,
which are then stored as application_url for jobs found via other sources
or as standalone discovered URLs.

No LinkedIn credentials are used or required.
"""
import logging
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.sources.base import JobSource, RawJob

logger = logging.getLogger(__name__)


class LinkedInDiscoverySource(JobSource):
    """
    Discovers LinkedIn job URLs through Google public search via SerpAPI.

    LEGAL: Uses Google's public search results. Does NOT access LinkedIn directly.
    REQUIRES: SERPAPI_KEY environment variable (paid service ~$50/mo for 5k searches)
    WITHOUT KEY: This source is gracefully skipped. All other sources still work.
    """

    name = "LinkedInDiscovery"
    description = "Discovers LinkedIn job URLs via SerpAPI (Google public search)"
    SERPAPI_URL = "https://serpapi.com/search.json"

    def __init__(self, preferences: Dict[str, Any], search_settings: Dict[str, Any]):
        super().__init__(preferences, search_settings)
        self.api_key = get_settings().serpapi_key

    async def search(self) -> List[RawJob]:
        if not self.api_key:
            logger.info(
                "LinkedInDiscovery: SERPAPI_KEY not configured — skipping. "
                "LinkedIn URL discovery requires a SerpAPI key."
            )
            return []

        jobs: List[RawJob] = []
        queries = self.build_search_queries()

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            for query in queries[:3]:
                try:
                    results = await self._search_google(client, query)
                    jobs.extend(results)
                except Exception as e:
                    logger.warning(f"LinkedInDiscovery error for '{query}': {e!r}")

                if len(jobs) >= self.max_jobs:
                    break

        return jobs

    async def _search_google(self, client: httpx.AsyncClient, query: str) -> List[RawJob]:
        """Search Google for LinkedIn job URLs via SerpAPI."""
        resp = await client.get(
            self.SERPAPI_URL,
            params={
                "api_key": self.api_key,
                "engine": "google",
                "q": f'site:linkedin.com/jobs/view "{query}" India',
                "num": 10,
                "hl": "en",
                "gl": "in",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        jobs = []
        for result in data.get("organic_results", []):
            url = result.get("link", "")
            if "linkedin.com/jobs/view" not in url:
                continue

            title = result.get("title", "").replace(" - LinkedIn", "").strip()
            snippet = result.get("snippet", "")

            # Extract company from snippet or title
            company = _extract_company_from_snippet(snippet, title)

            job = RawJob(
                title=title or query,
                company=company or "Unknown (via LinkedIn)",
                source=self.name,
                job_url=url,
                application_url=url,
                linkedin_url=url,
                description=snippet,
                location=_extract_location_from_snippet(snippet),
                source_job_id=_extract_linkedin_job_id(url),
                raw_data={"serpapi_result": result},
            )
            jobs.append(job)

        return jobs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_linkedin_job_id(url: str) -> Optional[str]:
    """Extract LinkedIn job ID from URL."""
    match = re.search(r"/jobs/view/(\d+)", url)
    return match.group(1) if match else None


def _extract_company_from_snippet(snippet: str, title: str) -> Optional[str]:
    """Try to extract company name from Google snippet text."""
    # Pattern: "Company Name · Location" or "at Company Name"
    patterns = [
        r"^([^·]+)·",
        r" at ([A-Z][^·\n]+)",
        r"([A-Z][a-zA-Z\s]+(?:Inc|Ltd|Limited|Technologies|Tech|Solutions|Systems|Services))",
    ]
    for pattern in patterns:
        match = re.search(pattern, snippet)
        if match:
            return match.group(1).strip()
    return None


def _extract_location_from_snippet(snippet: str) -> Optional[str]:
    """Try to extract location from snippet."""
    india_cities = [
        "Bangalore", "Bengaluru", "Mumbai", "Hyderabad", "Pune",
        "Chennai", "Delhi", "Noida", "Gurgaon", "Gurugram",
        "Kolkata", "India", "Remote"
    ]
    for city in india_cities:
        if city.lower() in snippet.lower():
            return city
    return "India"
