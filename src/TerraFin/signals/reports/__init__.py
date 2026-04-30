"""Scheduled narrative briefings (weekly digest, etc.)."""
from .storage import StoredReport, list_reports, load_report
from .weekly import build_weekly_report

__all__ = ["build_weekly_report", "list_reports", "load_report", "StoredReport"]
