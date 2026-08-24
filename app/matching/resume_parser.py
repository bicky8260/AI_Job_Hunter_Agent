"""
Resume parser — extracts structured information from a PDF resume.

Extracted fields:
- skills, technologies, cloud_platforms, devops_tools
- programming_languages, certifications
- education, projects
- years_of_experience
- Full profile JSON for LLM context
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known term sets for extraction
# ---------------------------------------------------------------------------

CLOUD_PLATFORMS = {
    "gcp", "google cloud", "google cloud platform", "aws", "amazon web services",
    "azure", "microsoft azure", "cloud", "cloud run", "gke", "eks", "aks",
    "cloud functions", "lambda", "ec2", "s3", "bigquery", "cloud storage",
    "cloud build", "artifact registry",
}

DEVOPS_TOOLS = {
    "docker", "kubernetes", "k8s", "terraform", "helm", "argo cd", "argocd",
    "jenkins", "gitlab ci", "gitlab ci/cd", "github actions", "circleci",
    "ansible", "chef", "puppet", "salt", "packer", "vagrant",
    "prometheus", "grafana", "dynatrace", "datadog", "new relic", "elk",
    "elasticsearch", "kibana", "logstash", "splunk", "istio", "envoy",
    "vault", "consul", "nomad", "linux", "bash", "shell",
    "git", "svn", "maven", "gradle", "sonarqube", "nexus", "artifactory",
    "terraform cloud", "opentofu", "pulumi", "crossplane",
}

PROGRAMMING_LANGUAGES = {
    "python", "java", "go", "golang", "javascript", "typescript", "ruby",
    "rust", "scala", "kotlin", "c", "c++", "c#", "php", "bash", "shell",
    "powershell", "groovy", "hcl", "yaml", "json",
}

CERTIFICATIONS = [
    "cka", "ckad", "cks", "aws certified", "google cloud certified",
    "azure certified", "gcp professional", "kubernetes certified",
    "hashicorp certified", "terraform associate", "devops professional",
    "solutions architect", "sysops administrator", "cloud practitioner",
    "professional cloud", "associate cloud",
]

EXPERIENCE_PATTERNS = [
    r"(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)",
    r"(?:experience|exp)\s*(?:of\s+)?(\d+)\+?\s*(?:years?|yrs?)",
    r"(\d{4})\s*[-–—]\s*(?:present|current|now|\d{4})",  # date range
]

EDUCATION_KEYWORDS = [
    "b.tech", "btech", "b.e.", "be", "bachelor", "b.sc", "bsc",
    "m.tech", "mtech", "m.e.", "me", "master", "m.sc", "msc",
    "phd", "ph.d", "mba", "diploma", "certification",
    "computer science", "information technology", "electronics",
    "electrical", "engineering",
]


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class ResumeParser:
    """Parses a PDF resume and extracts structured information."""

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)

    def parse(self) -> Dict[str, Any]:
        """
        Parse the resume and return a structured profile dict.
        Returns empty dict if parsing fails.
        """
        try:
            text = self._extract_text()
            if not text:
                logger.warning(f"No text extracted from {self.pdf_path}")
                return {}

            profile = {
                "raw_text": text,
                "skills": self._extract_skills(text),
                "technologies": self._extract_technologies(text),
                "cloud_platforms": self._extract_cloud_platforms(text),
                "devops_tools": self._extract_devops_tools(text),
                "programming_languages": self._extract_programming_languages(text),
                "certifications": self._extract_certifications(text),
                "education": self._extract_education(text),
                "projects": self._extract_projects(text),
                "years_of_experience": self._estimate_experience(text),
                "parsed_at": datetime.now(timezone.utc).isoformat(),
            }

            # Build a flattened skills list for easy matching
            all_skills = set()
            all_skills.update(profile["skills"])
            all_skills.update(profile["technologies"])
            all_skills.update(profile["cloud_platforms"])
            all_skills.update(profile["devops_tools"])
            all_skills.update(profile["programming_languages"])
            profile["all_skills_flat"] = sorted(all_skills)

            logger.info(
                f"Resume parsed: {len(profile['all_skills_flat'])} skills found, "
                f"~{profile['years_of_experience']} years experience"
            )
            return profile

        except Exception as e:
            logger.error(f"Resume parsing failed: {e!r}")
            return {}

    def _extract_text(self) -> str:
        """Extract text from PDF using pdfplumber (preferred) with pypdf fallback."""
        text = ""

        # Try pdfplumber first (better for formatted PDFs)
        try:
            import pdfplumber
            with pdfplumber.open(str(self.pdf_path)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                text = "\n".join(pages_text)
        except Exception as e:
            logger.debug(f"pdfplumber failed, trying pypdf: {e!r}")

        # Fallback to pypdf
        if not text:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(self.pdf_path))
                pages_text = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                text = "\n".join(pages_text)
            except Exception as e:
                logger.error(f"pypdf also failed: {e!r}")

        return text.strip()

    def _extract_skills(self, text: str) -> List[str]:
        """Extract all technical skills mentioned in the resume."""
        all_known = CLOUD_PLATFORMS | DEVOPS_TOOLS | PROGRAMMING_LANGUAGES
        found = []
        text_lower = text.lower()
        for skill in all_known:
            if skill in text_lower:
                # Preserve original casing from skill set
                found.append(skill.title() if len(skill) <= 3 else skill)
        return sorted(set(found))

    def _extract_technologies(self, text: str) -> List[str]:
        """Extract technology names."""
        techs = []
        patterns = [
            r'\b(Kubernetes|Docker|Terraform|Helm|Ansible|Jenkins|GitLab|ArgoCD|Prometheus|Grafana)\b',
            r'\b(GCP|AWS|Azure|GKE|EKS|AKS)\b',
            r'\b(Python|Java|Go|Golang|JavaScript|TypeScript|Bash)\b',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            techs.extend(matches)
        return sorted(set(techs))

    def _extract_cloud_platforms(self, text: str) -> List[str]:
        """Extract cloud platform mentions."""
        found = []
        text_lower = text.lower()
        for platform in CLOUD_PLATFORMS:
            if platform in text_lower:
                found.append(platform)
        return sorted(set(found))

    def _extract_devops_tools(self, text: str) -> List[str]:
        """Extract DevOps tool mentions."""
        found = []
        text_lower = text.lower()
        for tool in DEVOPS_TOOLS:
            if tool in text_lower:
                found.append(tool)
        return sorted(set(found))

    def _extract_programming_languages(self, text: str) -> List[str]:
        """Extract programming language mentions."""
        found = []
        text_lower = text.lower()
        for lang in PROGRAMMING_LANGUAGES:
            if lang in text_lower:
                found.append(lang)
        return sorted(set(found))

    def _extract_certifications(self, text: str) -> List[str]:
        """Extract certification mentions."""
        found = []
        text_lower = text.lower()
        for cert in CERTIFICATIONS:
            if cert in text_lower:
                # Try to get the full certification name from context
                idx = text_lower.find(cert)
                context = text[max(0, idx-10):idx+80].strip()
                found.append(context[:80])
        return found

    def _extract_education(self, text: str) -> List[Dict[str, str]]:
        """Extract education entries."""
        education = []
        lines = text.split("\n")
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in EDUCATION_KEYWORDS):
                edu_entry = {
                    "raw": line.strip(),
                    "context": " ".join(lines[max(0, i-1):i+3]).strip(),
                }
                education.append(edu_entry)
        return education[:5]  # cap at 5

    def _extract_projects(self, text: str) -> List[Dict[str, str]]:
        """Extract project descriptions."""
        projects = []
        # Look for project sections
        project_section = re.search(
            r"(?:projects?|personal projects?|key projects?)[:\s]*\n(.*?)(?:\n\n|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if project_section:
            project_text = project_section.group(1)
            # Split by bullet points or numbered items
            items = re.split(r"[•\-\*]|\n\d+[\.\)]\s+", project_text)
            for item in items:
                item = item.strip()
                if len(item) > 20:
                    projects.append({"description": item[:500]})
        return projects[:10]

    def _estimate_experience(self, text: str) -> float:
        """
        Estimate total years of experience from the resume.
        Tries multiple strategies:
        1. Explicit mentions ("3 years of experience")
        2. Date ranges in work history
        3. Number of roles
        """
        text_lower = text.lower()

        # Strategy 1: Explicit mention
        for pattern in EXPERIENCE_PATTERNS[:2]:
            matches = re.findall(pattern, text_lower)
            if matches:
                try:
                    return float(matches[0])
                except (ValueError, IndexError):
                    pass

        # Strategy 2: Date ranges
        date_ranges = re.findall(
            r"(\d{4})\s*[-–—]\s*(present|current|\d{4})",
            text,
            re.IGNORECASE,
        )
        total_years = 0.0
        current_year = datetime.now().year
        for start, end in date_ranges:
            try:
                start_year = int(start)
                end_year = current_year if end.lower() in ("present", "current") else int(end)
                if 1990 <= start_year <= current_year and end_year >= start_year:
                    total_years += end_year - start_year
            except ValueError:
                pass

        if total_years > 0:
            return min(total_years, 20.0)  # cap at 20

        # Strategy 3: Default
        return 2.0  # assume mid-level if unknown


def parse_resume_file(file_path: str) -> Dict[str, Any]:
    """Convenience function to parse a resume file."""
    parser = ResumeParser(file_path)
    return parser.parse()
