"""Tests for the Excel/CSV/Markdown sink."""

from __future__ import annotations

import pandas as pd

from chubb_ci.schemas.models import DiffEvent, EventType, ProductRecord
from chubb_ci.sinks.excel_sink import ExcelSink
from chubb_ci.summary.facts import ReportDraft


def test_write_report_creates_markdown(tmp_path):
    sink = ExcelSink(tmp_path)
    draft = ReportDraft(title="测试报告", content_md="# 测试报告\n\n内容", num_events=0)
    path = sink.write_report(draft, report_type="daily")
    assert path.exists()
    assert "测试报告" in path.read_text(encoding="utf-8")


def test_export_tables_writes_xlsx_and_csv(tmp_path):
    sink = ExcelSink(tmp_path)
    events = [
        DiffEvent(company="甲", event_type=EventType.PRICE_CHANGE.value,
                  product_name="A系列", field="price", old_value="1000",
                  new_value="800", pct_change=-20.0),
    ]
    products = [ProductRecord(company="甲", product_name="A系列", price=800.0, currency="CNY")]
    paths = sink.export_tables(events=events, products=products, run_id=1)

    xlsx = next(p for p in paths if p.suffix == ".xlsx")
    csv = next(p for p in paths if p.suffix == ".csv")
    assert xlsx.exists() and csv.exists()

    changes = pd.read_excel(xlsx, sheet_name="Changes")
    assert changes.iloc[0]["product_name"] == "A系列"
    assert changes.iloc[0]["pct_change"] == -20.0
    products_sheet = pd.read_excel(xlsx, sheet_name="Products")
    assert products_sheet.iloc[0]["price"] == 800.0


def test_export_handles_empty(tmp_path):
    sink = ExcelSink(tmp_path)
    paths = sink.export_tables(events=[], products=[], run_id=None)
    assert all(p.exists() for p in paths)
