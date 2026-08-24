"""
Email notification system.

Sends formatted HTML emails with matching jobs.
Uses SMTP (Gmail by default) with configurable credentials.
Supports a "test mode" that saves email to disk instead of sending.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def get_jinja_env() -> Environment:
    """Create Jinja2 environment for email templates."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def group_jobs_by_category(jobs: List[Dict[str, Any]]) -> tuple:
    """Split jobs into excellent/strong/good groups."""
    excellent = [j for j in jobs if j["total_score"] >= 90]
    strong = [j for j in jobs if 80 <= j["total_score"] < 90]
    good = [j for j in jobs if 70 <= j["total_score"] < 80]
    return excellent, strong, good


def build_email_subject(matched_count: int, run_date: str) -> str:
    """Build the email subject line."""
    return f"[AI Job Hunter] {matched_count} New DevOps Job{'s' if matched_count != 1 else ''} Found — {run_date}"


def render_email_html(
    jobs: List[Dict[str, Any]],
    run_stats: Dict[str, Any],
    settings=None,
) -> str:
    """Render the HTML email from the Jinja2 template."""
    if settings is None:
        settings = get_settings()

    env = get_jinja_env()
    template = env.get_template("email.html")

    excellent, strong, good = group_jobs_by_category(jobs)
    run_date = datetime.now(timezone.utc).strftime("%d %b %Y")

    context = {
        "recipient_name": settings.email_recipient_name,
        "run_date": run_date,
        "jobs": jobs,
        "excellent_matches": excellent,
        "strong_matches": strong,
        "good_matches": good,
        "total_found": run_stats.get("total_found", 0),
        "total_unique": run_stats.get("total_unique", 0),
        "total_matched": len(jobs),
        "total_rejected": run_stats.get("total_rejected", 0),
        "already_sent": run_stats.get("already_sent", 0),
        "source_stats": run_stats.get("source_stats", {}),
    }

    return template.render(**context)


def build_plain_text_email(jobs: List[Dict[str, Any]], run_stats: Dict[str, Any]) -> str:
    """Build a plain-text fallback version of the email."""
    lines = []
    lines.append("=" * 60)
    lines.append("AI JOB HUNTER — Daily Job Report")
    lines.append(f"Date: {datetime.now().strftime('%d %b %Y')}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Found: {run_stats.get('total_found', 0)} | Matched: {len(jobs)} | Rejected: {run_stats.get('total_rejected', 0)}")
    lines.append("")

    for i, job in enumerate(jobs, 1):
        lines.append(f"{i}. {job['title']}")
        lines.append(f"   Company:    {job['company']}")
        lines.append(f"   Location:   {job.get('location', 'Not specified')}")
        lines.append(f"   Work Mode:  {job.get('work_mode', 'Not specified')}")
        lines.append(f"   Experience: {job.get('experience_raw', 'Not specified')}")
        lines.append(f"   Salary:     {job.get('salary_raw', 'Not specified')}")
        lines.append(f"   Match:      {job['total_score']}/100 ({job.get('match_category', '')})")
        if job.get("skills_matched"):
            lines.append(f"   Skills:     {', '.join(job['skills_matched'][:6])}")
        if job.get("match_reasons"):
            lines.append("   Why this matches:")
            for reason in job["match_reasons"][:3]:
                lines.append(f"     - {reason}")
        lines.append(f"   Apply:      {job.get('application_url') or job.get('job_url', 'N/A')}")
        lines.append("")

    lines.append("-" * 40)
    lines.append("Summary")
    lines.append(f"New jobs found:    {run_stats.get('total_found', 0)}")
    lines.append(f"Matching jobs:     {len(jobs)}")
    lines.append(f"Rejected:          {run_stats.get('total_rejected', 0)}")
    lines.append(f"Already sent:      {run_stats.get('already_sent', 0)}")

    return "\n".join(lines)


async def send_job_email(
    jobs: List[Dict[str, Any]],
    run_stats: Dict[str, Any],
    test_mode: bool = False,
) -> bool:
    """
    Send the daily job email.

    Args:
        jobs: List of matched job dicts (with scores and match info)
        run_stats: Stats about this search run
        test_mode: If True, save to disk instead of sending

    Returns:
        True if sent successfully, False otherwise
    """
    settings = get_settings()

    if not jobs and not settings.send_empty_email:
        logger.info("No matching jobs — skipping email")
        return True

    matched_count = len(jobs)
    run_date = datetime.now().strftime("%d %b %Y")
    subject = build_email_subject(matched_count, run_date)

    # Render HTML
    try:
        html_body = render_email_html(jobs, run_stats, settings)
    except Exception as e:
        logger.error(f"Failed to render email template: {e!r}")
        html_body = "<p>Error rendering email template.</p>"

    # Plain text fallback
    text_body = build_plain_text_email(jobs, run_stats)

    # Test mode — save to disk
    if test_mode:
        return _save_test_email(subject, html_body, text_body)

    # Check email is configured
    if not settings.is_email_configured:
        logger.warning("Email not configured (EMAIL_USERNAME/EMAIL_PASSWORD/EMAIL_TO missing) — saving to disk")
        return _save_test_email(subject, html_body, text_body)

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from or settings.email_username
    msg["To"] = settings.email_to

    # Add both plain text and HTML parts
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Send via SMTP
    try:
        import ssl
        import certifi
        # macOS needs explicit SSL context pointing to certifi CA bundle
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        await aiosmtplib.send(
            msg,
            hostname=settings.email_host,
            port=settings.email_port,
            username=settings.email_username,
            password=settings.email_password,
            use_tls=False,
            start_tls=True,
            tls_context=ssl_context,
        )
        logger.info(f"Email sent successfully: '{subject}' to {settings.email_to}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e!r}")
        # Try to save locally as fallback
        _save_test_email(subject, html_body, text_body, prefix="failed_")
        return False


def _save_test_email(
    subject: str,
    html_body: str,
    text_body: str,
    prefix: str = "test_",
) -> bool:
    """Save email to disk for testing/debugging."""
    try:
        output_dir = Path("email_output")
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save HTML
        html_path = output_dir / f"{prefix}email_{timestamp}.html"
        html_path.write_text(html_body, encoding="utf-8")

        # Save plain text
        txt_path = output_dir / f"{prefix}email_{timestamp}.txt"
        txt_path.write_text(f"Subject: {subject}\n\n{text_body}", encoding="utf-8")

        logger.info(f"Test email saved: {html_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save test email: {e!r}")
        return False


async def send_test_email() -> bool:
    """
    Send a test email with sample data.
    Useful for verifying email configuration.
    """
    sample_jobs = [
        {
            "title": "DevOps Engineer",
            "company": "Test Technologies Pvt Ltd",
            "location": "Remote India",
            "work_mode": "Remote",
            "experience_min_years": 1,
            "experience_max_years": 3,
            "experience_raw": "1-3 years",
            "salary_raw": "₹10-14 LPA",
            "salary_min_inr": 1_000_000,
            "salary_max_inr": 1_400_000,
            "employment_type": "Full-time",
            "source": "TestSource",
            "total_score": 94,
            "match_category": "Excellent Match",
            "skills_matched": ["Kubernetes", "GCP", "Terraform", "Docker", "GitLab CI/CD"],
            "skills_missing": ["AWS"],
            "match_reasons": [
                "Strong Kubernetes experience match",
                "GCP/GKE requirement matches your profile",
                "Terraform IaC requirement aligns well",
                "Remote work matches preference",
            ],
            "application_url": "https://example.com/apply/devops-engineer",
            "job_url": "https://example.com/jobs/devops-engineer",
            "linkedin_url": None,
        },
    ]

    run_stats = {
        "total_found": 12,
        "total_unique": 9,
        "total_matched": 1,
        "total_rejected": 8,
        "already_sent": 3,
        "source_stats": {"RemoteOK": 5, "Naukri": 4, "Arbeitnow": 3},
    }

    settings = get_settings()
    is_test = not settings.is_email_configured

    return await send_job_email(sample_jobs, run_stats, test_mode=is_test)
