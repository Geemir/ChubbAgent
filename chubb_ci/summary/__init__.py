"""Executive summaries: deterministic fact assembly + LLM narrative."""

from chubb_ci.summary.daily import build_daily_report
from chubb_ci.summary.facts import ReportDraft, WeeklyStats, aggregate_week, format_events_facts
from chubb_ci.summary.weekly import build_weekly_report

__all__ = [
    "build_daily_report",
    "build_weekly_report",
    "ReportDraft",
    "WeeklyStats",
    "aggregate_week",
    "format_events_facts",
]
