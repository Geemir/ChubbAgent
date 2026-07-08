"""Excel / CSV / Markdown sink — the default marketing-facing output."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from chubb_ci.schemas.models import DiffEvent, ProductRecord
from chubb_ci.summary.facts import ReportDraft

_EVENT_COLUMNS = [
    "company", "event_type", "product_name", "field",
    "old_value", "new_value", "pct_change", "channel", "source_url", "detected_at",
]
_PRODUCT_COLUMNS = [
    "company", "product_name", "category", "price", "currency", "promotion",
    "promotion_end_date", "availability", "gb_grade", "euro_grade", "fire_rating",
    "capacity_l", "lock_type", "source_url", "crawl_time",
]


class ExcelSink:
    """Writes reports (.md) and tabular exports (.xlsx + .csv) to a directory."""

    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _stamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def write_report(self, draft: ReportDraft, *, report_type: str) -> Path:
        path = self.out_dir / f"{self._stamp()}_report_{report_type}.md"
        path.write_text(draft.content_md, encoding="utf-8")
        logger.info("report written: {}", path)
        return path

    def export_tables(
        self, *, events: list[DiffEvent], products: list[ProductRecord], run_id: int | None
    ) -> list[Path]:
        stamp = self._stamp()
        paths: list[Path] = []

        events_df = self._events_df(events)
        products_df = self._products_df(products)

        # Combined workbook (two sheets) for convenience.
        xlsx = self.out_dir / f"{stamp}_competitive_intel.xlsx"
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            events_df.to_excel(writer, sheet_name="Changes", index=False)
            products_df.to_excel(writer, sheet_name="Products", index=False)
        paths.append(xlsx)

        # CSV for lightweight sharing / import.
        events_csv = self.out_dir / f"{stamp}_changes.csv"
        events_df.to_csv(events_csv, index=False, encoding="utf-8-sig")
        paths.append(events_csv)

        logger.info("exported {} events, {} products to {}", len(events), len(products), self.out_dir)
        return paths

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clean(value: Any) -> Any:
        # Excel rejects tz-aware datetimes; flatten lists for a single cell.
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        if isinstance(value, (list, tuple)):
            return "；".join(str(v) for v in value)
        return value

    @classmethod
    def _events_df(cls, events: list[DiffEvent]) -> pd.DataFrame:
        rows = [{c: cls._clean(getattr(e, c, None)) for c in _EVENT_COLUMNS} for e in events]
        return pd.DataFrame(rows, columns=_EVENT_COLUMNS)

    @classmethod
    def _products_df(cls, products: list[ProductRecord]) -> pd.DataFrame:
        rows = [{c: cls._clean(getattr(p, c, None)) for c in _PRODUCT_COLUMNS} for p in products]
        return pd.DataFrame(rows, columns=_PRODUCT_COLUMNS)
