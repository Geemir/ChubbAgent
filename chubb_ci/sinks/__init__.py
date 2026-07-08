"""Output sinks: make results consumable by the marketing team.

SQLite is the source of truth (see storage/). Sinks are the *shareable* layer:
Excel/CSV/Markdown today; Google Sheets / Notion are stubs behind the same interface.
"""

from chubb_ci.sinks.base import ReportSink
from chubb_ci.sinks.excel_sink import ExcelSink

__all__ = ["ReportSink", "ExcelSink"]
