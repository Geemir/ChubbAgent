"""Test the real-data loader (no fabricated competitors, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chubb_ci.storage.db import session_scope
from chubb_ci.storage.repositories import Repository
from chubb_ci.tools.load_real import load_real

DECK = Path(__file__).resolve().parents[1] / "CompetitorAnalysisV7.pptx"
CATALOG = Path(__file__).resolve().parents[1] / "ChubbProductsList.xlsx"


@pytest.mark.skipif(not (DECK.exists() and CATALOG.exists()),
                    reason="real source files not present")
def test_load_real_no_fabricated_competitors(settings):
    # crawl=False → deterministic, offline (deck + catalog + brands only).
    result = load_real(settings, crawl=False)
    assert result["deck_products"] > 0
    assert result["own_products"] > 40
    assert result["brands"] >= 9

    with session_scope(settings) as s:
        repo = Repository(s)
        companies = {p.company for p in repo.all_products()}
        # fabricated demo competitors must NOT be present
        assert "演示竞品 Demo" not in companies
        assert "大一 Dayi" not in companies          # demo-only brand
        # real deck brands ARE present
        assert "德国百卫特 Burg Wächter" in companies
        assert "福美德 Format" in companies
