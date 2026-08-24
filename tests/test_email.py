"""
Tests for the email generation system.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import os

from app.notifications.email import (
    build_email_subject,
    build_plain_text_email,
    group_jobs_by_category,
    render_email_html,
)


# ─── Sample data ─────────────────────────────────────────────────────────────

SAMPLE_JOBS = [
    {
        "title": "DevOps Engineer",
        "company": "Tech Corp",
        "location": "Remote India",
        "work_mode": "Remote",
        "experience_min_years": 1,
        "experience_max_years": 3,
        "experience_raw": "1-3 years",
        "salary_raw": "₹10-14 LPA",
        "salary_min_inr": 1_000_000,
        "salary_max_inr": 1_400_000,
        "employment_type": "Full-time",
        "source": "RemoteOK",
        "total_score": 94,
        "match_category": "Excellent Match",
        "skills_matched": ["Kubernetes", "GCP", "Terraform"],
        "skills_missing": ["AWS"],
        "match_reasons": ["Strong Kubernetes match", "GCP experience matches"],
        "application_url": "https://example.com/apply/1",
        "job_url": "https://example.com/job/1",
        "linkedin_url": None,
    },
    {
        "title": "Site Reliability Engineer",
        "company": "SRE Inc",
        "location": "Hyderabad / Remote",
        "work_mode": "Hybrid",
        "experience_raw": "2-4 years",
        "experience_min_years": 2,
        "experience_max_years": 4,
        "salary_raw": None,
        "employment_type": "Full-time",
        "source": "Naukri",
        "total_score": 82,
        "match_category": "Strong Match",
        "skills_matched": ["Kubernetes", "Docker"],
        "skills_missing": ["Ansible"],
        "match_reasons": ["SRE role matches experience"],
        "application_url": "https://example.com/apply/2",
        "job_url": "https://example.com/job/2",
        "linkedin_url": "https://linkedin.com/jobs/view/99999",
    },
    {
        "title": "Cloud Engineer",
        "company": "Cloud Tech",
        "location": "Remote",
        "work_mode": "Remote",
        "experience_raw": "1-2 years",
        "experience_min_years": 1,
        "experience_max_years": 2,
        "salary_raw": "₹8-12 LPA",
        "employment_type": "Full-time",
        "source": "Arbeitnow",
        "total_score": 76,
        "match_category": "Good Match",
        "skills_matched": ["GCP", "Docker"],
        "skills_missing": [],
        "match_reasons": ["Cloud focus matches GCP skills"],
        "application_url": "https://example.com/apply/3",
        "job_url": None,
        "linkedin_url": None,
    },
]

SAMPLE_RUN_STATS = {
    "total_found": 20,
    "total_unique": 15,
    "total_matched": 3,
    "total_rejected": 12,
    "already_sent": 5,
    "source_stats": {"RemoteOK": 8, "Naukri": 7},
}


# ─── Subject line ─────────────────────────────────────────────────────────────

class TestEmailSubject:

    def test_subject_format_multiple_jobs(self):
        subject = build_email_subject(7, "22 Aug 2026")
        assert "[AI Job Hunter]" in subject
        assert "7 New DevOps Jobs" in subject
        assert "22 Aug 2026" in subject

    def test_subject_singular_job(self):
        subject = build_email_subject(1, "22 Aug 2026")
        assert "1 New DevOps Job Found" in subject
        assert "Jobs" not in subject  # singular

    def test_subject_zero_jobs(self):
        subject = build_email_subject(0, "22 Aug 2026")
        assert "0" in subject


# ─── Job grouping ─────────────────────────────────────────────────────────────

class TestJobGrouping:

    def test_groups_by_score(self):
        excellent, strong, good = group_jobs_by_category(SAMPLE_JOBS)
        assert len(excellent) == 1
        assert len(strong) == 1
        assert len(good) == 1
        assert excellent[0]["total_score"] == 94
        assert strong[0]["total_score"] == 82
        assert good[0]["total_score"] == 76

    def test_empty_list(self):
        excellent, strong, good = group_jobs_by_category([])
        assert excellent == []
        assert strong == []
        assert good == []


# ─── Plain text rendering ─────────────────────────────────────────────────────

class TestPlainTextEmail:

    def test_contains_job_titles(self):
        text = build_plain_text_email(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "DevOps Engineer" in text
        assert "Site Reliability Engineer" in text
        assert "Cloud Engineer" in text

    def test_contains_company_names(self):
        text = build_plain_text_email(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "Tech Corp" in text
        assert "SRE Inc" in text

    def test_contains_scores(self):
        text = build_plain_text_email(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "94/100" in text
        assert "82/100" in text

    def test_contains_summary(self):
        text = build_plain_text_email(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "Summary" in text
        assert "20" in text  # total_found


# ─── HTML rendering ───────────────────────────────────────────────────────────

class TestHTMLEmailRendering:

    def test_html_renders_without_error(self):
        """HTML template should render without exceptions."""
        html = render_email_html(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert isinstance(html, str)
        assert len(html) > 100

    def test_html_contains_job_info(self):
        html = render_email_html(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "DevOps Engineer" in html
        assert "Tech Corp" in html

    def test_html_contains_apply_links(self):
        html = render_email_html(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "https://example.com/apply/1" in html

    def test_html_contains_linkedin_link(self):
        html = render_email_html(SAMPLE_JOBS, SAMPLE_RUN_STATS)
        assert "linkedin.com" in html

    def test_html_empty_job_list(self):
        """Email renders even with no jobs (no-match day)."""
        html = render_email_html([], SAMPLE_RUN_STATS)
        assert isinstance(html, str)
        assert "No new matching jobs" in html


# ─── Test mode email saving ───────────────────────────────────────────────────

class TestEmailSendTestMode:

    @pytest.mark.asyncio
    async def test_test_mode_saves_to_disk(self, tmp_path, monkeypatch):
        """In test mode, email should be saved to disk."""
        monkeypatch.chdir(tmp_path)

        from app.notifications.email import send_job_email
        result = await send_job_email(SAMPLE_JOBS, SAMPLE_RUN_STATS, test_mode=True)

        assert result is True
        # Check that files were created
        email_dir = tmp_path / "email_output"
        assert email_dir.exists()
        html_files = list(email_dir.glob("*.html"))
        assert len(html_files) >= 1
