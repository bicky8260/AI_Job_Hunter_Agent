"""
Sources package — registers all available job source adapters.
"""
from app.sources.base import JobSource, RawJob
from app.sources.job_boards import (
    AdzunaSource,
    ArbeitnowSource,
    JoobleSource,
    RemoteOKSource,
    TheMuseSource,
)
from app.sources.company_careers import CompanyCareersSource
from app.sources.naukri import NaukriSource
from app.sources.linkedin_discovery import LinkedInDiscoverySource
from app.sources.public_search import PublicSearchSource

__all__ = [
    "JobSource",
    "RawJob",
    "RemoteOKSource",
    "ArbeitnowSource",
    "AdzunaSource",
    "JoobleSource",
    "TheMuseSource",
    "CompanyCareersSource",
    "NaukriSource",
    "LinkedInDiscoverySource",
    "PublicSearchSource",
    "get_all_sources",
]


def get_all_sources(preferences: dict, search_settings: dict) -> list:
    """
    Return all enabled job source adapter instances.
    Sources that fail to initialize are skipped gracefully.
    """
    source_classes = [
        RemoteOKSource,
        ArbeitnowSource,
        NaukriSource,
        AdzunaSource,
        JoobleSource,
        TheMuseSource,
        PublicSearchSource,
        CompanyCareersSource,
        LinkedInDiscoverySource,
    ]

    sources = []
    for cls in source_classes:
        try:
            sources.append(cls(preferences, search_settings))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to init {cls.__name__}: {e!r}")

    return sources
