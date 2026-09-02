"""
Base job source abstraction.
All job source adapters inherit from JobSource.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RawJob:
    """
    Normalized raw job data from any source.
    Fields are optional — sources provide what they can.
    The agent will attempt to extract missing fields via LLM.
    """
    # Required
    title: str
    company: str
    source: str  # source adapter name

    # Highly recommended
    job_url: Optional[str] = None
    application_url: Optional[str] = None
    description: Optional[str] = None

    # Location
    location: Optional[str] = None
    work_mode: Optional[str] = None  # Remote | Hybrid | On-site

    # Salary
    salary_raw: Optional[str] = None
    salary_min_inr: Optional[int] = None
    salary_max_inr: Optional[int] = None
    salary_currency: Optional[str] = None

    # Experience
    experience_min_years: Optional[float] = None
    experience_max_years: Optional[float] = None
    experience_raw: Optional[str] = None

    # Employment
    employment_type: Optional[str] = None  # Full-time | Part-time | Contract

    # Skills
    required_skills: List[str] = field(default_factory=list)
    preferred_skills: List[str] = field(default_factory=list)

    # Dates
    posted_date: Optional[datetime] = None
    application_deadline: Optional[datetime] = None

    # URLs
    company_url: Optional[str] = None
    linkedin_url: Optional[str] = None

    # Source-specific
    source_job_id: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.source_job_id is not None:
            self.source_job_id = str(self.source_job_id)

    def __repr__(self) -> str:
        return f"RawJob(title={self.title!r}, company={self.company!r}, source={self.source!r})"


class JobSource(ABC):
    """
    Abstract base class for all job source adapters.

    Each adapter is responsible for:
    1. Searching for jobs matching the given preferences
    2. Returning a list of RawJob objects
    3. Handling its own errors gracefully (never raising)
    4. Respecting rate limits and access controls
    """

    name: str = "BaseSource"
    description: str = "Base job source"
    enabled: bool = True

    def __init__(self, preferences: Dict[str, Any], search_settings: Dict[str, Any]):
        self.preferences = preferences
        self.search_settings = search_settings
        self.logger = logging.getLogger(f"sources.{self.name}")

    @abstractmethod
    async def search(self) -> List[RawJob]:
        """
        Search for jobs and return a list of RawJob objects.
        Must NEVER raise an exception — catch internally and return [].
        """
        ...

    async def safe_search(self) -> List[RawJob]:
        """
        Wrapper that ensures exceptions are logged but never propagate.
        The agent uses this instead of search() directly.
        """
        try:
            logger.info(f"Source: {self.name} — starting search")
            results = await self.search()
            logger.info(f"Source: {self.name} — found {len(results)} jobs")
            return results
        except Exception as e:
            logger.warning(f"Source: {self.name} — FAILED: {e!r}")
            return []

    @property
    def job_titles(self) -> List[str]:
        return self.preferences.get("job_titles", [])

    @property
    def locations(self) -> List[str]:
        return self.preferences.get("locations", [])

    @property
    def max_jobs(self) -> int:
        return self.search_settings.get("max_jobs_per_source", 50)

    @property
    def request_timeout(self) -> int:
        return self.search_settings.get("request_timeout_seconds", 30)

    @property
    def max_age_days(self) -> int:
        return self.search_settings.get("max_job_age_days", 7)

    def build_search_queries(self) -> List[str]:
        """Build a list of search query strings from job preferences."""
        titles = self.job_titles[:4]  # limit to avoid too many requests
        return titles
