"""
Job preferences API routes.

GET /preferences — return current preferences from config.yaml
PUT /preferences — update preferences in config.yaml
"""
import logging
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_job_preferences, get_settings, reload_config_yaml

logger = logging.getLogger(__name__)
router = APIRouter()


class PreferencesUpdate(BaseModel):
    job_preferences: Dict[str, Any]


@router.get("/preferences")
async def get_preferences():
    """Return current job preferences from config.yaml."""
    prefs = get_job_preferences()
    return {
        "preferences": prefs,
        "config_file": get_settings().config_yaml_path,
    }


@router.put("/preferences")
async def update_preferences(update: PreferencesUpdate):
    """
    Update job preferences in config.yaml.
    Reloads config immediately after saving.
    """
    settings = get_settings()
    config_path = settings.config_yaml_path

    try:
        # Load current config
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        # Update preferences section
        config["job_preferences"] = update.job_preferences

        # Save back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Reload config cache
        reload_config_yaml()

        logger.info("Job preferences updated via API")
        return {
            "message": "Preferences updated successfully",
            "preferences": update.job_preferences,
        }

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config file not found: {config_path}")
    except Exception as e:
        logger.error(f"Failed to update preferences: {e!r}")
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {str(e)}")
