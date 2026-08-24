"""
Tests for the job matching and scoring engine.
"""
import pytest
from unittest.mock import patch

from app.sources.base import RawJob
from app.matching.scoring import (
    calculate_match_score,
    get_match_category,
    skills_match,
    match_skill_lists,
    score_title,
    score_skills,
    score_experience,
    score_location,
    score_salary,
)



# ─── Skill synonym matching ───────────────────────────────────────────────────

class TestSkillMatching:

    def test_exact_skill_match(self):
        assert skills_match("Kubernetes", "Kubernetes") is True

    def test_case_insensitive_match(self):
        assert skills_match("kubernetes", "KUBERNETES") is True

    def test_synonym_match_gke_gcp(self):
        """GKE should match GCP (GKE is a GCP product)."""
        assert skills_match("GKE", "GCP") is True

    def test_synonym_match_gke_google_cloud(self):
        """GKE should match Google Cloud."""
        assert skills_match("GKE", "Google Cloud") is True

    def test_synonym_match_k8s_kubernetes(self):
        """k8s should match Kubernetes."""
        assert skills_match("k8s", "Kubernetes") is True

    def test_synonym_match_terraform_iac(self):
        """Terraform should match Infrastructure as Code."""
        assert skills_match("Terraform", "Infrastructure as Code") is True

    def test_synonym_match_gcp(self):
        """GCP should match Google Cloud Platform."""
        assert skills_match("GCP", "Google Cloud Platform") is True

    def test_synonym_match_argocd(self):
        """ArgoCD should match Argo CD."""
        assert skills_match("ArgoCD", "Argo CD") is True

    def test_no_match_unrelated(self):
        """AWS should not match Kubernetes."""
        assert skills_match("AWS", "Kubernetes") is False

    def test_fuzzy_partial_match(self):
        """Kubernetes should fuzzy-match k8s."""
        assert skills_match("k8s", "Kubernetes") is True

    def test_match_skill_lists_returns_matched_and_missing(self):
        resume = ["Kubernetes", "GCP", "Terraform", "Docker"]
        job = ["Kubernetes", "GCP", "AWS", "Ansible"]
        matched, missing = match_skill_lists(resume, job)
        assert "Kubernetes" in matched
        assert "GCP" in matched
        assert "AWS" in missing
        assert "Ansible" in missing


# ─── Title scoring ────────────────────────────────────────────────────────────

class TestTitleScoring:

    def test_exact_title_match(self, sample_preferences):
        job = RawJob(title="DevOps Engineer", company="X", source="test")
        score, reasons = score_title(job, sample_preferences)
        assert score == 20
        assert "Exact title match" in reasons[0]

    def test_partial_title_match(self, sample_preferences):
        job = RawJob(title="Junior DevOps Engineer", company="X", source="test")
        score, _ = score_title(job, sample_preferences)
        assert 10 <= score <= 20

    def test_excluded_title_returns_zero(self, sample_preferences):
        job = RawJob(title="Senior DevOps Engineer", company="X", source="test")
        score, reasons = score_title(job, sample_preferences)
        assert score == 0
        assert "Excluded" in reasons[0]

    def test_manager_title_excluded(self, sample_preferences):
        job = RawJob(title="DevOps Manager", company="X", source="test")
        score, _ = score_title(job, sample_preferences)
        assert score == 0

    def test_irrelevant_title_scores_low(self, sample_preferences):
        job = RawJob(title="Marketing Executive", company="X", source="test")
        score, _ = score_title(job, sample_preferences)
        assert score < 10


# ─── Experience scoring ───────────────────────────────────────────────────────

class TestExperienceScoring:

    def test_within_range_gets_full_score(self, sample_resume_profile):
        sample_resume_profile["years_of_experience"] = 2.0
        job = RawJob(
            title="X", company="Y", source="test",
            experience_min_years=1.0,
            experience_max_years=3.0,
        )
        score, reasons = score_experience(job, sample_resume_profile)
        assert score == 15
        assert "matches" in reasons[0].lower()

    def test_under_experience_penalized(self, sample_resume_profile):
        sample_resume_profile["years_of_experience"] = 0.5
        job = RawJob(
            title="X", company="Y", source="test",
            experience_min_years=2.0,
            experience_max_years=4.0,
        )
        score, _ = score_experience(job, sample_resume_profile)
        assert score < 15

    def test_no_experience_stated_partial_score(self, sample_resume_profile):
        job = RawJob(title="X", company="Y", source="test")
        score, _ = score_experience(job, sample_resume_profile)
        assert 5 <= score <= 15

    def test_over_experienced_not_harshly_penalized(self, sample_resume_profile):
        sample_resume_profile["years_of_experience"] = 5.0
        job = RawJob(
            title="X", company="Y", source="test",
            experience_min_years=1.0,
            experience_max_years=3.0,
        )
        score, _ = score_experience(job, sample_resume_profile)
        assert score >= 10  # should not be heavily penalized


# ─── Location scoring ─────────────────────────────────────────────────────────

class TestLocationScoring:

    def test_remote_match(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", location="Remote", work_mode="Remote")
        score, _ = score_location(job, sample_preferences)
        assert score >= 12

    def test_india_location(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", location="Bangalore, India")
        score, _ = score_location(job, sample_preferences)
        assert score >= 7

    def test_non_india_location_low_score(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", location="New York, USA", work_mode="On-site")
        score, _ = score_location(job, sample_preferences)
        assert score <= 8


# ─── Salary scoring ───────────────────────────────────────────────────────────

class TestSalaryScoring:

    def test_above_minimum_gets_full_score(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", salary_min_inr=1_500_000)
        score, _ = score_salary(job, sample_preferences)
        assert score == 10

    def test_at_minimum_gets_full_score(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", salary_min_inr=1_000_000)
        score, _ = score_salary(job, sample_preferences)
        assert score == 10

    def test_below_minimum_penalized(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test", salary_min_inr=500_000)
        score, _ = score_salary(job, sample_preferences)
        assert score < 10

    def test_no_salary_partial_score(self, sample_preferences):
        job = RawJob(title="X", company="Y", source="test")
        score, reasons = score_salary(job, sample_preferences)
        assert score == 5
        assert "not specified" in reasons[0].lower()


# ─── Full match score ─────────────────────────────────────────────────────────

class TestFullMatchScore:

    def test_perfect_match_scores_high(self, sample_job, sample_resume_profile, sample_preferences):
        result = calculate_match_score(sample_job, sample_resume_profile, sample_preferences)
        assert result["total_score"] >= 70
        assert result["match_category"] in ["Excellent Match", "Strong Match", "Good Match"]

    def test_excluded_title_scores_zero(self, sample_resume_profile, sample_preferences):
        job = RawJob(title="Senior DevOps Engineer", company="X", source="test")
        result = calculate_match_score(job, sample_resume_profile, sample_preferences)
        assert result["total_score"] == 0
        assert result["match_category"] == "Excluded"

    def test_irrelevant_job_scores_low(self, sample_resume_profile, sample_preferences):
        job = RawJob(
            title="Marketing Manager",
            company="X",
            source="test",
            location="New York",
        )
        result = calculate_match_score(job, sample_resume_profile, sample_preferences)
        assert result["total_score"] < 60

    def test_skills_matched_returned(self, sample_job, sample_resume_profile, sample_preferences):
        result = calculate_match_score(sample_job, sample_resume_profile, sample_preferences)
        assert isinstance(result["skills_matched"], list)
        assert len(result["skills_matched"]) > 0


# ─── Match category ───────────────────────────────────────────────────────────

class TestMatchCategory:

    @pytest.mark.parametrize("score,expected", [
        (95, "Excellent Match"),
        (85, "Strong Match"),
        (75, "Good Match"),
        (65, "Possible Match"),
        (45, "No Match"),
    ])
    def test_categories(self, score, expected):
        category, _ = get_match_category(score)
        assert category == expected
