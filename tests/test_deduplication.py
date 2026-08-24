"""
Tests for job deduplication logic.
"""
import pytest

from app.sources.base import RawJob
from app.agents.job_agent import (
    make_canonical_id,
    normalize_title,
    normalize_company,
    deduplicate_raw_jobs,
)


class TestNormalization:

    def test_normalize_title_lowercase(self):
        assert normalize_title("DevOps Engineer") == normalize_title("devops engineer")

    def test_normalize_title_removes_noise(self):
        t1 = normalize_title("DevOps Engineer (Urgent Hiring)")
        t2 = normalize_title("DevOps Engineer")
        assert t1 == t2

    def test_normalize_company_removes_suffixes(self):
        c1 = normalize_company("Tech Corp Pvt Ltd")
        c2 = normalize_company("Tech Corp")
        assert c1 == c2

    def test_normalize_company_lowercase(self):
        assert normalize_company("Google") == normalize_company("GOOGLE")


class TestCanonicalId:

    def test_same_job_same_id(self):
        id1 = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://example.com/job/123")
        id2 = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://example.com/job/123")
        assert id1 == id2

    def test_same_job_different_case_same_id(self):
        id1 = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://example.com/job/123")
        id2 = make_canonical_id("devops engineer", "tech corp", "remote", "https://example.com/job/123")
        assert id1 == id2

    def test_different_company_different_id(self):
        id1 = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://a.com/job/1")
        id2 = make_canonical_id("DevOps Engineer", "Other Corp", "Remote", "https://b.com/job/1")
        assert id1 != id2

    def test_different_title_different_id(self):
        id1 = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://a.com/1")
        id2 = make_canonical_id("SRE", "Tech Corp", "Remote", "https://b.com/2")
        assert id1 != id2

    def test_id_is_hex_string(self):
        cid = make_canonical_id("DevOps Engineer", "Tech Corp", "Remote", "https://x.com")
        assert isinstance(cid, str)
        assert len(cid) == 32  # 32 hex chars from SHA256[:32]


class TestDeduplication:

    def _make_job(self, title, company, url, source="S1", location="Remote"):
        return RawJob(
            title=title,
            company=company,
            source=source,
            application_url=url,
            location=location,
        )

    def test_removes_exact_duplicate(self):
        job1 = self._make_job("DevOps Engineer", "Tech Corp", "https://example.com/1")
        job2 = self._make_job("DevOps Engineer", "Tech Corp", "https://example.com/1")
        result = deduplicate_raw_jobs([job1, job2])
        assert len(result) == 1

    def test_keeps_different_companies(self):
        job1 = self._make_job("DevOps Engineer", "Corp A", "https://corp-a.com/1")
        job2 = self._make_job("DevOps Engineer", "Corp B", "https://corp-b.com/2")
        result = deduplicate_raw_jobs([job1, job2])
        assert len(result) == 2

    def test_dedup_by_url(self):
        """Same URL from two sources → keep one."""
        job1 = self._make_job("DevOps Eng", "Corp", "https://example.com/job/99", source="S1")
        job2 = self._make_job("DevOps Engineer", "Corp", "https://example.com/job/99", source="S2")
        result = deduplicate_raw_jobs([job1, job2])
        assert len(result) == 1

    def test_merges_linkedin_url(self):
        """If one job has LinkedIn URL and same canonical_id, merge it."""
        job1 = self._make_job("SRE", "Corp", "https://corp.com/sre")
        job2 = self._make_job("SRE", "Corp", "https://corp.com/sre")
        job2.linkedin_url = "https://linkedin.com/jobs/view/12345"
        result = deduplicate_raw_jobs([job1, job2])
        assert len(result) == 1
        # LinkedIn URL should be merged into the surviving job
        assert result[0].linkedin_url == "https://linkedin.com/jobs/view/12345"

    def test_empty_list(self):
        assert deduplicate_raw_jobs([]) == []

    def test_single_job_unchanged(self):
        job = self._make_job("SRE", "Corp", "https://x.com/1")
        result = deduplicate_raw_jobs([job])
        assert len(result) == 1
        assert result[0] is job

    def test_large_list_deduplication(self):
        """Test performance and correctness on larger lists."""
        jobs = []
        for i in range(20):
            # 10 unique + 10 duplicates
            url = f"https://example.com/job/{i % 10}"
            jobs.append(self._make_job(f"DevOps Engineer {i}", "Corp", url))
        result = deduplicate_raw_jobs(jobs)
        assert len(result) == 10
