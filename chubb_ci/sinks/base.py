"""ReportSink protocol — swap output destinations without touching the pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from chubb_ci.schemas.models import DiffEvent, ProductRecord
from chubb_ci.summary.facts import ReportDraft


@runtime_checkable
class ReportSink(Protocol):
    """Persist a generated report and export the supporting tables."""

    def write_report(self, draft: ReportDraft, *, report_type: str) -> Path:
        """Write the report (e.g. Markdown) and return its path."""
        ...

    def export_tables(
        self, *, events: list[DiffEvent], products: list[ProductRecord], run_id: int | None
    ) -> list[Path]:
        """Export change events + product snapshot as tabular files. Return paths."""
        ...
