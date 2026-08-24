"""
Scoring engine — calculates the 0-100 match score between a job and a resume.

Score breakdown:
  Title relevance:     20 pts
  Technical skills:    30 pts
  Experience match:    15 pts
  Location/work-mode:  15 pts
  Salary match:        10 pts
  Overall relevance:   10 pts
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from app.config import get_skill_synonyms
from app.sources.base import RawJob


# ---------------------------------------------------------------------------
# Category thresholds
# ---------------------------------------------------------------------------

EXCELLENT = (90, 100, "Excellent Match", "🔥")
STRONG    = (80,  89, "Strong Match",    "💼")
GOOD      = (70,  79, "Good Match",      "👍")
POSSIBLE  = (60,  69, "Possible Match",  "🤔")
NO_MATCH  = (0,   59, "No Match",        "❌")


def get_match_category(score: int) -> Tuple[str, str]:
    """Return (category_label, emoji) for a score."""
    for lo, hi, label, emoji in [EXCELLENT, STRONG, GOOD, POSSIBLE, NO_MATCH]:
        if lo <= score <= hi:
            return label, emoji
    return "No Match", "❌"


# ---------------------------------------------------------------------------
# Skill synonym resolution
# ---------------------------------------------------------------------------

def build_skill_alias_map() -> Dict[str, str]:
    """
    Build a flat map: alias_lower → canonical_skill_name
    e.g. "gke" → "kubernetes", "iac" → "terraform"
    """
    synonyms = get_skill_synonyms()
    alias_map = {}
    for canonical, aliases in synonyms.items():
        for alias in aliases:
            alias_map[alias.lower()] = canonical
    return alias_map


_ALIAS_MAP: Optional[Dict[str, str]] = None


def get_alias_map() -> Dict[str, str]:
    global _ALIAS_MAP
    if _ALIAS_MAP is None:
        _ALIAS_MAP = build_skill_alias_map()
    return _ALIAS_MAP


def resolve_skill(skill: str) -> str:
    """Resolve a skill to its canonical name using synonym map."""
    alias_map = get_alias_map()
    return alias_map.get(skill.lower(), skill.lower())


def skills_match(resume_skill: str, job_skill: str) -> bool:
    """
    Check if two skill terms refer to the same technology.
    Uses synonym resolution + fuzzy matching.
    """
    r = resolve_skill(resume_skill)
    j = resolve_skill(job_skill)

    # Exact canonical match
    if r == j:
        return True

    # Fuzzy match (handles typos, partial names)
    ratio = fuzz.partial_ratio(r, j)
    return ratio >= 85


def match_skill_lists(resume_skills: List[str], job_skills: List[str]) -> Tuple[List[str], List[str]]:
    """
    Compare resume skills to job requirements.
    Returns (matched_skills, missing_skills).
    """
    matched = []
    missing = []

    for job_skill in job_skills:
        found = False
        for resume_skill in resume_skills:
            if skills_match(resume_skill, job_skill):
                matched.append(job_skill)
                found = True
                break
        if not found:
            missing.append(job_skill)

    return matched, missing


# ---------------------------------------------------------------------------
# Individual score components
# ---------------------------------------------------------------------------

def score_title(job: RawJob, preferences: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Score title relevance (0-20).
    Checks: title matches preferred_titles, doesn't match exclude_titles.
    """
    job_title_lower = job.title.lower()
    preferred_titles = [t.lower() for t in preferences.get("job_titles", [])]
    exclude_titles = [t.lower() for t in preferences.get("exclude_titles", [])]

    reasons = []
    score = 0

    # Check exclusions first
    for exc in exclude_titles:
        if exc in job_title_lower:
            return 0, [f"Excluded title: '{exc}' found in '{job.title}'"]

    # Exact match
    for title in preferred_titles:
        if title == job_title_lower:
            score = 20
            reasons.append(f"Exact title match: '{job.title}'")
            break

    # Partial match
    if score == 0:
        for title in preferred_titles:
            if title in job_title_lower or job_title_lower in title:
                score = 15
                reasons.append(f"Partial title match: '{job.title}' ≈ '{title}'")
                break

    # Fuzzy match
    if score == 0:
        best_ratio = max(
            (fuzz.partial_ratio(job_title_lower, t) for t in preferred_titles),
            default=0,
        )
        if best_ratio >= 80:
            score = 12
            reasons.append(f"Fuzzy title match ({best_ratio}%): '{job.title}'")
        elif best_ratio >= 60:
            score = 6
            reasons.append(f"Weak title match ({best_ratio}%): '{job.title}'")

    if score == 0:
        reasons.append(f"Title '{job.title}' not in preferred list")

    return min(score, 20), reasons


def score_skills(
    job: RawJob,
    resume_profile: Dict[str, Any],
    preferences: Dict[str, Any],
) -> Tuple[int, List[str], List[str], List[str]]:
    """
    Score technical skill match (0-30).
    Returns (score, reasons, matched_skills, missing_skills).
    """
    resume_skills = resume_profile.get("all_skills_flat", [])
    pref_skills = preferences.get("preferred_skills", [])

    # Combine: job's required + preferred skills
    job_required = list(job.required_skills or [])
    job_preferred = list(job.preferred_skills or [])

    # If no skills extracted from job, use preference skills as target
    all_job_skills = job_required or (pref_skills[:10] if not job_preferred else job_preferred)

    if not all_job_skills:
        return 15, ["No specific skills listed — awarding partial score"], [], []

    matched, missing = match_skill_lists(resume_skills, all_job_skills)

    total_skills = len(all_job_skills)
    match_ratio = len(matched) / total_skills if total_skills > 0 else 0

    score = int(match_ratio * 30)

    reasons = []
    if matched:
        reasons.append(f"Matched {len(matched)}/{total_skills} required skills: {', '.join(matched[:5])}")
    if missing:
        reasons.append(f"Missing: {', '.join(missing[:3])}")

    return min(score, 30), reasons, matched, missing


def score_experience(job: RawJob, resume_profile: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Score experience match (0-15)."""
    resume_years = resume_profile.get("years_of_experience", 2.0)
    job_min = job.experience_min_years
    job_max = job.experience_max_years

    reasons = []

    if job_min is None and job_max is None:
        return 10, ["Experience not specified — awarding partial score"]

    # Within range
    if job_min is not None and job_max is not None:
        if job_min <= resume_years <= job_max:
            return 15, [f"Experience {resume_years:.0f}y matches requirement {job_min:.0f}-{job_max:.0f}y"]
        elif resume_years < job_min:
            gap = job_min - resume_years
            score = max(0, 15 - int(gap * 5))
            return score, [f"Under-experienced: {resume_years:.0f}y vs {job_min:.0f}y minimum"]
        else:
            # Over-experienced — not penalized as much
            return 12, [f"Slightly over-experienced: {resume_years:.0f}y vs max {job_max:.0f}y"]

    if job_min is not None:
        if resume_years >= job_min:
            return 15, [f"Meets minimum experience ({resume_years:.0f}y ≥ {job_min:.0f}y)"]
        else:
            gap = job_min - resume_years
            return max(0, 15 - int(gap * 5)), [f"Below minimum experience: {resume_years:.0f}y < {job_min:.0f}y"]

    return 10, ["Partial experience info — awarding partial score"]


def score_location(job: RawJob, preferences: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Score location and work mode match (0-15)."""
    pref_locations = [l.lower() for l in preferences.get("locations", [])]
    pref_work_modes = [w.lower() for w in preferences.get("work_mode", [])]

    job_location = (job.location or "").lower()
    job_work_mode = (job.work_mode or "").lower()

    reasons = []
    score = 0

    # Check work mode
    work_mode_score = 0
    for wm in pref_work_modes:
        if wm in job_work_mode or wm in job_location:
            work_mode_score = 8
            reasons.append(f"Work mode '{job.work_mode or job_location}' matches preference")
            break

    # Check location
    location_score = 0
    for loc in pref_locations:
        if loc in job_location:
            location_score = 7
            reasons.append(f"Location '{job.location}' matches preference")
            break

    score = work_mode_score + location_score

    if score == 0:
        # Partial credit if India is mentioned at all
        if "india" in job_location or "remote" in job_location:
            score = 7
            reasons.append(f"Location '{job.location}' is India/Remote")
        else:
            reasons.append(f"Location '{job.location}' doesn't match preferences")

    return min(score, 15), reasons


def score_salary(job: RawJob, preferences: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Score salary match (0-10)."""
    min_salary = preferences.get("minimum_salary_inr", 1_000_000)
    job_min_inr = job.salary_min_inr

    if job_min_inr is None:
        # Can't penalize for missing salary info — give neutral score
        return 5, ["Salary not specified"]

    if job_min_inr >= min_salary:
        return 10, [f"Salary ≥ ₹{min_salary:,} minimum ({_format_lpa(job_min_inr)} LPA offered)"]
    elif job_min_inr >= min_salary * 0.8:
        return 6, [f"Salary slightly below minimum ({_format_lpa(job_min_inr)} LPA offered)"]
    else:
        return 2, [f"Salary below minimum: {_format_lpa(job_min_inr)} LPA < {_format_lpa(min_salary)} LPA minimum"]


def score_overall_relevance(job: RawJob, resume_profile: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Score overall role relevance (0-10).
    Checks description for DevOps/cloud context clues.
    """
    description = (job.description or "").lower()
    resume_skills = set(s.lower() for s in resume_profile.get("all_skills_flat", []))

    devops_indicators = {
        "kubernetes", "terraform", "ci/cd", "pipeline", "infrastructure",
        "deployment", "cloud", "monitoring", "automation", "docker",
        "microservices", "service mesh", "observability", "on-call",
        "sre", "platform", "devops", "gitops", "helm",
    }

    hits = sum(1 for ind in devops_indicators if ind in description)

    if hits >= 8:
        return 10, ["Highly relevant DevOps/cloud role based on description"]
    elif hits >= 5:
        return 8, ["Relevant DevOps/cloud role"]
    elif hits >= 3:
        return 5, ["Somewhat relevant to DevOps/cloud"]
    elif hits >= 1:
        return 2, ["Minimal DevOps relevance in description"]
    else:
        return 0, ["No clear DevOps relevance found in description"]


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

def calculate_match_score(
    job: RawJob,
    resume_profile: Dict[str, Any],
    preferences: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calculate the full 0-100 match score for a job.

    Returns a dict with:
    - total_score
    - component scores
    - match_category, emoji
    - match_reasons (list of strings)
    - gaps (list of strings)
    - skills_matched, skills_missing
    """
    title_score, title_reasons = score_title(job, preferences)

    # If title is excluded, return 0 immediately
    if title_score == 0 and any("Excluded" in r for r in title_reasons):
        return {
            "total_score": 0,
            "title_score": 0,
            "skills_score": 0,
            "experience_score": 0,
            "location_score": 0,
            "salary_score": 0,
            "relevance_score": 0,
            "match_category": "Excluded",
            "emoji": "🚫",
            "match_reasons": title_reasons,
            "gaps": [],
            "skills_matched": [],
            "skills_missing": [],
        }

    skills_score, skills_reasons, matched, missing = score_skills(job, resume_profile, preferences)
    exp_score, exp_reasons = score_experience(job, resume_profile)
    loc_score, loc_reasons = score_location(job, preferences)
    sal_score, sal_reasons = score_salary(job, preferences)
    rel_score, rel_reasons = score_overall_relevance(job, resume_profile)

    total = title_score + skills_score + exp_score + loc_score + sal_score + rel_score
    category, emoji = get_match_category(total)

    # Build human-readable reasons
    all_reasons = title_reasons + skills_reasons + exp_reasons + loc_reasons
    gaps = [r for r in (sal_reasons + skills_reasons) if any(
        kw in r.lower() for kw in ["missing", "below", "not specified", "gap"]
    )]

    return {
        "total_score": total,
        "title_score": title_score,
        "skills_score": skills_score,
        "experience_score": exp_score,
        "location_score": loc_score,
        "salary_score": sal_score,
        "relevance_score": rel_score,
        "match_category": category,
        "emoji": emoji,
        "match_reasons": [r for r in all_reasons if r and "not in" not in r.lower()],
        "gaps": gaps,
        "skills_matched": matched,
        "skills_missing": missing,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_lpa(inr: int) -> str:
    """Format INR to LPA string."""
    lpa = inr / 100_000
    return f"₹{lpa:.0f}"
