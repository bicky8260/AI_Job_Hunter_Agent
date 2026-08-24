"""
Resume API routes.

POST /resume/upload — upload and parse a PDF resume
GET  /resume        — get parsed resume data
"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.database import get_db
from app.database.models import ResumeData
from app.matching.resume_parser import parse_resume_file

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a PDF resume.
    The file will be parsed and skills/experience extracted for matching.
    """
    settings = get_settings()

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Ensure upload directory exists
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / settings.resume_filename

    # Save file
    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        if len(content) > 10 * 1024 * 1024:  # 10 MB limit
            raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

        save_path.write_bytes(content)
        logger.info(f"Resume saved: {save_path} ({len(content)} bytes)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Parse resume
    try:
        profile = parse_resume_file(str(save_path))
        if not profile:
            logger.warning("Resume parsed but no data extracted")
    except Exception as e:
        logger.error(f"Resume parsing error: {e!r}")
        profile = {}

    # Save to database
    try:
        result = await db.execute(select(ResumeData).where(ResumeData.id == 1))
        resume_data = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if resume_data is None:
            resume_data = ResumeData(id=1)
            db.add(resume_data)

        resume_data.filename = file.filename
        resume_data.raw_text = profile.get("raw_text", "")
        resume_data.skills = profile.get("skills", [])
        resume_data.technologies = profile.get("technologies", [])
        resume_data.cloud_platforms = profile.get("cloud_platforms", [])
        resume_data.devops_tools = profile.get("devops_tools", [])
        resume_data.programming_languages = profile.get("programming_languages", [])
        resume_data.certifications = profile.get("certifications", [])
        resume_data.education = profile.get("education", [])
        resume_data.projects = profile.get("projects", [])
        resume_data.years_of_experience = profile.get("years_of_experience", 2.0)
        resume_data.profile_json = profile
        resume_data.uploaded_at = now
        resume_data.parsed_at = now

        await db.flush()

    except Exception as e:
        logger.error(f"Failed to save resume to DB: {e!r}")
        raise HTTPException(status_code=500, detail="Resume parsed but could not be saved to database")

    return {
        "message": "Resume uploaded and parsed successfully",
        "filename": file.filename,
        "skills_found": len(profile.get("all_skills_flat", [])),
        "years_of_experience": profile.get("years_of_experience"),
        "cloud_platforms": profile.get("cloud_platforms", []),
        "devops_tools": profile.get("devops_tools", [])[:10],
        "certifications": profile.get("certifications", []),
    }


@router.get("/resume")
async def get_resume(db: AsyncSession = Depends(get_db)):
    """Get the currently uploaded and parsed resume data."""
    result = await db.execute(select(ResumeData).where(ResumeData.id == 1))
    resume = result.scalar_one_or_none()

    if not resume:
        return {
            "resume_uploaded": False,
            "message": "No resume uploaded yet. Use POST /resume/upload to upload a PDF.",
        }

    return {
        "resume_uploaded": True,
        "filename": resume.filename,
        "uploaded_at": resume.uploaded_at.isoformat() if resume.uploaded_at else None,
        "parsed_at": resume.parsed_at.isoformat() if resume.parsed_at else None,
        "years_of_experience": resume.years_of_experience,
        "skills": resume.skills,
        "technologies": resume.technologies,
        "cloud_platforms": resume.cloud_platforms,
        "devops_tools": resume.devops_tools,
        "programming_languages": resume.programming_languages,
        "certifications": resume.certifications,
        "education": resume.education,
    }
