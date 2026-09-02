"""
Application configuration.
Loads from .env file and config.yaml.
All settings are accessible via the `settings` singleton.
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://jobhunter:jobhunter@localhost:5432/jobhunter",
        description="Async PostgreSQL connection string",
    )

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    email_host: str = Field(default="smtp.gmail.com")
    email_port: int = Field(default=587)
    email_username: str = Field(default="")
    email_password: str = Field(default="")
    email_from: str = Field(default="")
    email_to: str = Field(default="")
    email_recipient_name: str = Field(default="Biswa")
    send_empty_email: bool = Field(default=False)

    # ------------------------------------------------------------------
    # LLM Provider
    # ------------------------------------------------------------------
    llm_provider: str = Field(default="mock", description="gemini | openai | mock")
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")

    # ------------------------------------------------------------------
    # Job Source API Keys (all optional)
    # ------------------------------------------------------------------
    adzuna_app_id: str = Field(default="")
    adzuna_app_key: str = Field(default="")
    jooble_api_key: str = Field(default="")
    serpapi_key: str = Field(default="")

    # ------------------------------------------------------------------
    # App Settings
    # ------------------------------------------------------------------
    secret_key: str = Field(default="dev-secret-key-change-in-production")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Scheduler
    scheduler_timezone: str = Field(default="Asia/Kolkata")
    scheduler_hour: int = Field(default=9)
    scheduler_minute: int = Field(default=0)

    # Matching & Retention
    min_match_score: int = Field(default=70)
    job_retention_days: int = Field(default=10, description="Days after which jobs and runs are deleted")

    # File paths
    upload_dir: str = Field(default="uploads")
    resume_filename: str = Field(default="resume.pdf")

    # Config file path
    config_yaml_path: str = Field(default="config.yaml")

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"gemini", "openai", "mock"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got '{v}'")
        return v

    @property
    def resume_path(self) -> Path:
        return Path(self.upload_dir) / self.resume_filename

    @property
    def is_email_configured(self) -> bool:
        return bool(self.email_username and self.email_password and self.email_to)

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache()
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()


# ---------------------------------------------------------------------------
# Job preferences — loaded from config.yaml
# ---------------------------------------------------------------------------

_config_cache: Optional[Dict[str, Any]] = None


def load_config_yaml(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and cache the config.yaml file."""
    global _config_cache
    if _config_cache is None:
        config_path = path or get_settings().config_yaml_path
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f)
        except FileNotFoundError:
            _config_cache = {}
    return _config_cache


def reload_config_yaml() -> Dict[str, Any]:
    """Force reload of config.yaml (call after file is updated)."""
    global _config_cache
    _config_cache = None
    return load_config_yaml()


def get_job_preferences() -> Dict[str, Any]:
    """Return job preferences from config.yaml."""
    config = load_config_yaml()
    return config.get("job_preferences", {})


def get_search_settings() -> Dict[str, Any]:
    """Return search settings from config.yaml."""
    config = load_config_yaml()
    return config.get("search_settings", {})


def get_skill_synonyms() -> Dict[str, List[str]]:
    """Return skill synonym groups from config.yaml."""
    config = load_config_yaml()
    return config.get("skill_synonyms", {})


def get_company_career_pages() -> List[Dict[str, str]]:
    """Return list of company career page configs."""
    config = load_config_yaml()
    return config.get("company_career_pages", [])


# Make sure upload directory exists
def ensure_directories() -> None:
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)
