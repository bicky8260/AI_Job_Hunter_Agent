"""
AI Job Matcher — LLM-powered matching engine.

Provides a pluggable LLMProvider abstraction supporting:
  - GeminiProvider (Google Gemini)
  - OpenAIProvider (OpenAI)
  - MockProvider (rule-based, no API key required)

The JobMatcher orchestrates:
  1. Rule-based scoring (scoring.py)
  2. Optional LLM enrichment (job description parsing + skill extraction)
  3. Final score + reasoning generation
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.matching.scoring import calculate_match_score, get_match_category
from app.sources.base import RawJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Provider abstraction
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Send a prompt and return the text response."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is properly configured."""
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self):
        self.settings = get_settings()
        self._model = None
        self._disabled = False

    def is_available(self) -> bool:
        return bool(self.settings.gemini_api_key) and not self._disabled

    def _get_model(self):
        if self._disabled:
            return None
        if self._model is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.settings.gemini_api_key)
                self._model = genai.GenerativeModel(self.settings.gemini_model)
            except Exception as e:
                logger.error(f"Gemini init failed: {e!r}")
                self._disabled = True
                self._model = None
        return self._model

    async def complete(self, prompt: str) -> str:
        if self._disabled:
            return ""
        model = self._get_model()
        if not model:
            return ""
        try:
            # Gemini SDK is sync — run in executor for async compat
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, model.generate_content, prompt)
            return response.text or ""
        except Exception as e:
            logger.warning(f"Gemini LLM error ({e!r}). Disabling LLM for remaining jobs in this run (using rule-based scoring).")
            self._disabled = True
            return ""



class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self):
        self.settings = get_settings()
        self._client = None

    def is_available(self) -> bool:
        return bool(self.settings.openai_api_key)

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            except Exception as e:
                logger.error(f"OpenAI init failed: {e!r}")
        return self._client

    async def complete(self, prompt: str) -> str:
        client = self._get_client()
        if not client:
            return ""
        try:
            response = await client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"OpenAI completion failed: {e!r}")
            return ""


class MockProvider(LLMProvider):
    """
    Mock LLM provider for testing and when no API keys are configured.
    Uses simple rule-based logic — no API calls.
    """

    def is_available(self) -> bool:
        return True

    async def complete(self, prompt: str) -> str:
        # Return empty string — scorer will use rule-based results
        return ""


def get_llm_provider() -> LLMProvider:
    """Factory: return the configured LLM provider."""
    settings = get_settings()
    provider_name = settings.llm_provider.lower()

    if provider_name == "gemini":
        p = GeminiProvider()
        if p.is_available():
            return p
        logger.warning("Gemini requested but GEMINI_API_KEY not set — falling back to mock")

    elif provider_name == "openai":
        p = OpenAIProvider()
        if p.is_available():
            return p
        logger.warning("OpenAI requested but OPENAI_API_KEY not set — falling back to mock")

    return MockProvider()


# ---------------------------------------------------------------------------
# Job description enrichment via LLM
# ---------------------------------------------------------------------------

SKILL_EXTRACTION_PROMPT = """
You are a technical recruiter assistant. Extract structured information from this job posting.

Job Title: {title}
Company: {company}
Description:
{description}

Extract and return a JSON object with these exact fields:
{{
  "required_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill3", "skill4"],
  "experience_min_years": 1,
  "experience_max_years": 3,
  "work_mode": "Remote|Hybrid|On-site",
  "employment_type": "Full-time|Part-time|Contract",
  "salary_raw": "salary string or null",
  "summary": "2-3 sentence role summary"
}}

Rules:
- required_skills: only clearly required skills
- preferred_skills: nice-to-have skills
- If experience not mentioned, use null
- work_mode: infer from description if not stated
- Return ONLY valid JSON, no markdown, no extra text
"""

MATCH_REASONING_PROMPT = """
You are evaluating whether this job matches a candidate's profile.

Job: {title} at {company}
Location: {location}
Work Mode: {work_mode}
Required Skills: {required_skills}
Description: {description}

Candidate Profile:
Skills: {resume_skills}
Experience: {resume_experience} years
Cloud Platforms: {cloud_platforms}
DevOps Tools: {devops_tools}

Scoring (already calculated):
- Total Score: {total_score}/100
- Matched Skills: {matched_skills}
- Missing Skills: {missing_skills}

Write 3-5 concise bullet points explaining why this is or isn't a good match.
Focus on specific technical skill overlaps and gaps.
Return as a plain JSON array of strings:
["reason 1", "reason 2", "reason 3"]
"""


# ---------------------------------------------------------------------------
# JobMatcher
# ---------------------------------------------------------------------------

class JobMatcher:
    """
    Orchestrates job-resume matching using rule-based scoring + optional LLM enrichment.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider or get_llm_provider()

    async def enrich_job(self, job: RawJob) -> RawJob:
        """
        Use LLM to extract structured data from job description.
        Fills in missing fields like skills, experience, work_mode.
        Falls back gracefully if LLM fails.
        """
        if not job.description or len(job.description) < 50:
            return job

        if not self.llm.is_available() or isinstance(self.llm, MockProvider):
            return job  # skip LLM enrichment for mock

        prompt = SKILL_EXTRACTION_PROMPT.format(
            title=job.title,
            company=job.company,
            description=job.description[:3000],  # limit tokens
        )

        try:
            response = await self.llm.complete(prompt)
            if not response:
                return job

            # Parse JSON response
            data = _extract_json(response)
            if not data:
                return job

            # Fill in missing fields
            if not job.required_skills and data.get("required_skills"):
                job.required_skills = data["required_skills"]

            if not job.preferred_skills and data.get("preferred_skills"):
                job.preferred_skills = data["preferred_skills"]

            if job.experience_min_years is None and data.get("experience_min_years"):
                job.experience_min_years = float(data["experience_min_years"])

            if job.experience_max_years is None and data.get("experience_max_years"):
                job.experience_max_years = float(data["experience_max_years"])

            if not job.work_mode and data.get("work_mode"):
                job.work_mode = data["work_mode"]

            if not job.employment_type and data.get("employment_type"):
                job.employment_type = data["employment_type"]

            if not job.salary_raw and data.get("salary_raw"):
                job.salary_raw = data["salary_raw"]

        except Exception as e:
            logger.debug(f"Job enrichment failed for '{job.title}': {e!r}")

        return job

    async def match(
        self,
        job: RawJob,
        resume_profile: Dict[str, Any],
        preferences: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Calculate match score and generate reasoning for a job.

        Returns match result dict with:
        - total_score (0-100)
        - component scores
        - match_category, emoji
        - match_reasons list
        - gaps list
        - skills_matched, skills_missing
        - llm_summary (if LLM available)
        """
        # Step 1: Enrich job with LLM if available
        enriched_job = await self.enrich_job(job)

        # Step 2: Calculate rule-based score
        result = calculate_match_score(enriched_job, resume_profile, preferences)

        # Step 3: Optionally enhance reasoning with LLM
        if (
            result["total_score"] >= 50
            and not isinstance(self.llm, MockProvider)
            and self.llm.is_available()
        ):
            llm_reasons = await self._generate_reasons(enriched_job, resume_profile, result)
            if llm_reasons:
                result["match_reasons"] = llm_reasons

        return result

    async def _generate_reasons(
        self,
        job: RawJob,
        resume_profile: Dict[str, Any],
        score_result: Dict[str, Any],
    ) -> Optional[List[str]]:
        """Use LLM to generate human-readable match reasoning."""
        prompt = MATCH_REASONING_PROMPT.format(
            title=job.title,
            company=job.company,
            location=job.location or "Not specified",
            work_mode=job.work_mode or "Not specified",
            required_skills=", ".join(job.required_skills or []),
            description=(job.description or "")[:1500],
            resume_skills=", ".join(resume_profile.get("all_skills_flat", [])[:20]),
            resume_experience=resume_profile.get("years_of_experience", "unknown"),
            cloud_platforms=", ".join(resume_profile.get("cloud_platforms", [])),
            devops_tools=", ".join(resume_profile.get("devops_tools", [])),
            total_score=score_result["total_score"],
            matched_skills=", ".join(score_result.get("skills_matched", [])),
            missing_skills=", ".join(score_result.get("skills_missing", [])),
        )

        try:
            response = await self.llm.complete(prompt)
            reasons = _extract_json(response)
            if isinstance(reasons, list):
                return [str(r) for r in reasons[:5]]
        except Exception as e:
            logger.debug(f"Reason generation failed: {e!r}")

        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    if not text:
        return None

    # Remove markdown code blocks
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object/array in text
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    return None
