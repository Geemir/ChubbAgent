"""Alternative sink stubs (Google Sheets, Notion).

Left intentionally unimplemented: they satisfy the same :class:`ReportSink` protocol
so wiring one in later requires only implementing these two methods + a config flag —
no change to the pipeline. This demonstrates the replaceable-component design.
"""

from __future__ import annotations

from pathlib import Path

from chubb_ci.schemas.models import DiffEvent, ProductRecord
from chubb_ci.summary.facts import ReportDraft


class GoogleSheetsSink:
    """TODO: append changes/products to a shared Google Sheet via gspread."""

    def __init__(self, spreadsheet_id: str, credentials_path: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = credentials_path

    def write_report(self, draft: ReportDraft, *, report_type: str) -> Path:  # pragma: no cover
        raise NotImplementedError("GoogleSheetsSink not implemented in MVP")

    def export_tables(self, *, events: list[DiffEvent], products: list[ProductRecord], run_id):  # pragma: no cover
        raise NotImplementedError("GoogleSheetsSink not implemented in MVP")


class NotionSink:
    """TODO: create a report page + database rows via the Notion API."""

    def __init__(self, token: str, database_id: str) -> None:
        self.token = token
        self.database_id = database_id

    def write_report(self, draft: ReportDraft, *, report_type: str) -> Path:  # pragma: no cover
        raise NotImplementedError("NotionSink not implemented in MVP")

    def export_tables(self, *, events: list[DiffEvent], products: list[ProductRecord], run_id):  # pragma: no cover
        raise NotImplementedError("NotionSink not implemented in MVP")
