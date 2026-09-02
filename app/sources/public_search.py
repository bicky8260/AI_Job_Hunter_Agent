"""
Public search source — uses DuckDuckGo Instant Answer API and
public job board search pages to find jobs.

This is the fallback source that works without any API keys.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from app.sources.base import JobSource, RawJob

logger = logging.getLogger(__name__)


class PublicSearchSource(JobSource):
    """
    Uses public search APIs (DuckDuckGo, Indeed public pages)
    to discover job listings. No authentication required.
    """

    name = "PublicSearch"
    description = "Public job search (DuckDuckGo, public pages)"

    # Indeed public search (read-only, no login)
    INDEED_BASE = "https://www.indeed.com/jobs"
    NAUKRI_API = "https://www.naukri.com/jobapi/v3/search"

    async def search(self) -> List[RawJob]:
        jobs: List[RawJob] = []

        # Search Indeed India public listings
        indeed_jobs = await self._search_indeed()
        jobs.extend(indeed_jobs)

        return jobs[:self.max_jobs]

    async def _search_indeed(self) -> List[RawJob]:
        """Search Indeed India public job listings (HTML scraping of public pages)."""
        jobs = []
        queries = self.build_search_queries()

        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            verify=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            for query in queries[:2]:
                try:
                    resp = await client.get(
                        self.INDEED_BASE,
                        params={
                            "q": query,
                            "l": "India",
                            "sort": "date",
                            "fromage": str(self.max_age_days),
                        },
                    )

                    if resp.status_code != 200:
                        logger.info(f"Indeed returned {resp.status_code} for '{query}'")
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    parsed = self._parse_indeed_html(soup, query)
                    jobs.extend(parsed)
                    await asyncio.sleep(2)  # be polite

                except Exception as e:
                    logger.warning(f"Indeed search error for '{query}': {e!r}")

        return jobs

    def _parse_indeed_html(self, soup: BeautifulSoup, query: str) -> List[RawJob]:
        """Parse Indeed HTML search results page."""
        jobs = []
        # Indeed job cards
        cards = soup.find_all("div", {"class": re.compile(r"job_seen_beacon|jobsearch-SerpJobCard")})

        if not cards:
            # Try newer Indeed markup
            cards = soup.find_all("li", {"class": re.compile(r"css-.*job")})

        for card in cards[:15]:
            try:
                # Try multiple selector patterns (Indeed changes markup frequently)
                title_el = (
                    card.find("h2", {"class": re.compile(r"jobTitle|title")})
                    or card.find("a", {"class": re.compile(r"jobTitle")})
                )
                company_el = (
                    card.find("span", {"class": re.compile(r"companyName|company")})
                    or card.find("div", {"class": re.compile(r"company")})
                )
                location_el = card.find("div", {"class": re.compile(r"companyLocation|location")})
                salary_el = card.find("div", {"class": re.compile(r"salary|salaryOnly")})

                # Extract URL
                link_el = card.find("a", href=True)
                job_url = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        job_url = f"https://www.indeed.com{href}"
                    else:
                        job_url = href

                title = title_el.get_text(strip=True) if title_el else query
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                location = location_el.get_text(strip=True) if location_el else "India"
                salary_raw = salary_el.get_text(strip=True) if salary_el else None

                if not title or not company:
                    continue

                job = RawJob(
                    title=title,
                    company=company,
                    source=self.name,
                    job_url=job_url,
                    application_url=job_url,
                    location=location,
                    salary_raw=salary_raw,
                    raw_data={"html_card": True, "query": query},
                )
                jobs.append(job)

            except Exception as e:
                logger.debug(f"Error parsing Indeed card: {e!r}")

        return jobs


class FreelancerJobSource(JobSource):
    """
    Searches Freelancer.com job listings (public, no auth required).
    Useful for contract/remote DevOps gigs.
    """

    name = "FreelancerJobs"
    description = "Freelancer.com public job listings"
    BASE_URL = "https://www.freelancer.com/api/projects/0.1/projects/active/"
    SKILL_IDS = {
        "Docker": 922,
        "Kubernetes": 1063,
        "Terraform": 1126,
        "AWS": 80,
        "GCP": 1128,
        "Linux": 12,
        "Python": 13,
    }

    async def search(self) -> List[RawJob]:
        # Only include if employment types include contract
        emp_types = self.preferences.get("employment_types", [])
        if "Contract" not in emp_types and "Freelance" not in emp_types:
            return []

        jobs = []
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout, verify=False) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "job_ids[]": list(self.SKILL_IDS.values())[:5],
                        "limit": 20,
                        "offset": 0,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("result", {}).get("projects", []):
                    job = RawJob(
                        title=item.get("title", ""),
                        company="Freelancer.com",
                        source=self.name,
                        job_url=f"https://www.freelancer.com/projects/{item.get('seo_url', '')}",
                        application_url=f"https://www.freelancer.com/projects/{item.get('seo_url', '')}",
                        description=item.get("preview_description", ""),
                        work_mode="Remote",
                        employment_type="Contract",
                        raw_data=item,
                    )
                    jobs.append(job)
        except Exception as e:
            logger.warning(f"FreelancerJobs error: {e!r}")

        return jobs
