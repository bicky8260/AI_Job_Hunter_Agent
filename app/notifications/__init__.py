"""
Notifications package.
"""
from app.notifications.email import send_job_email, send_test_email

__all__ = ["send_job_email", "send_test_email"]
