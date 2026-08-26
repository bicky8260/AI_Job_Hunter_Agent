"""
Company career page scrapers for major India tech employers.
Only scrapes publicly accessible career pages — no login required.
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import get_company_career_pages
from app.sources.base import JobSource, RawJob

logger = logging.getLogger(__name__)

# Keywords to detect relevant DevOps/SRE/Cloud jobs
DEVOPS_KEYWORDS = [
    "devops", "sre", "site reliability", "cloud engineer", "platform engineer",
    "infrastructure engineer", "cloud devops", "kubernetes", "terraform", "gcp",
    "google cloud", "devsecops",
]


class CompanyCareersSource(JobSource):
    """
    Monitors public company career pages for DevOps/SRE job postings.
    Companies are configured in config.yaml under company_career_pages.
    """

    name = "CompanyCareers"
    description = "Public company career pages"

    async def search(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        company_pages = get_company_career_pages()

        async with httpx.AsyncClient(
            timeout=self.request_timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        ) as client:
            for company_config in company_pages[:10]:
                try:
                    company_jobs = await self._scrape_company(client, company_config)
                    jobs.extend(company_jobs)
                    logger.info(
                        f"CompanyCareers: {company_config['name']} → {len(company_jobs)} jobs"
                    )
                    await asyncio.sleep(2)  # polite delay between companies
                except Exception as e:
                    logger.warning(
                        f"CompanyCareers: {company_config.get('name', 'unknown')} FAILED: {e!r}"
                    )

                if len(jobs) >= self.max_jobs:
                    break

        return jobs

    async def _scrape_company(
        self, client: httpx.AsyncClient, config: Dict[str, str]
    ) -> List[RawJob]:
        """Dispatch to the right parser based on page type."""
        page_type = config.get("type", "generic")
        url = config["url"]
        company_name = config["name"]

        resp = await client.get(url)
        if resp.status_code != 200:
            logger.info(f"CompanyCareers: {company_name} returned {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        if page_type == "generic":
            return self._parse_generic(soup, company_name, url)
        else:
            return self._parse_generic(soup, company_name, url)

    def _parse_generic(
        self, soup: BeautifulSoup, company_name: str, base_url: str
    ) -> List[RawJob]:
        """Generic parser — finds job links on career pages."""
        jobs = []

        # Find all anchor tags that look like job postings
        links = soup.find_all("a", href=True)
        for link in links:
            text = link.get_text(strip=True)
            href = link["href"]

            if not text or len(text) < 5:
                continue

            # Check if this looks like a job title
            if not _is_relevant_job(text):
                continue

            # Build absolute URL
            if href.startswith("/"):
                job_url = urljoin(base_url, href)
            elif href.startswith("http"):
                job_url = href
            else:
                continue

            job = RawJob(
                title=text[:200],
                company=company_name,
                source=self.name,
                job_url=job_url,
                application_url=job_url,
                location="India",
                raw_data={"company_page": base_url},
            )
            jobs.append(job)

        return jobs[:20]  # cap per company



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_relevant_job(title: str) -> bool:
    """Check if a job title is relevant to DevOps/SRE/Cloud."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in DEVOPS_KEYWORDS)


def _parse_lpa_salary(salary_text: str) -> tuple:
    """
    Parse Indian LPA salary strings like '8-12 Lacs PA', '10 LPA', '₹10-14 LPA'.
    Returns (min_inr, max_inr) in absolute INR.
    """
    if not salary_text:
        return None, None

    # Extract numbers
    numbers = re.findall(r"[\d.]+", salary_text.lower().replace(",", ""))
    lakh = 100_000

    if len(numbers) >= 2:
        try:
            return int(float(numbers[0]) * lakh), int(float(numbers[1]) * lakh)
        except ValueError:
            pass
    elif len(numbers) == 1:
        try:
            val = int(float(numbers[0]) * lakh)
            return val, None
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

