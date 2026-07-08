"""Tests for the marketing-deck (PPTX) ingester value parsers + live deck parse."""

from __future__ import annotations

from pathlib import Path

import pytest

from chubb_ci.tools.pptx_ingest import _parse_price, _parse_sales, _route_cert, parse_deck

DECK = Path(__file__).resolve().parents[1] / "CompetitorAnalysisV7.pptx"


@pytest.mark.parametrize("text,expected", [
    ("￥5780", 5780.0),
    ("￥60,000+", 60000.0),
    ("￥7,500~26,000+", 7500.0),          # range → low end
    ("皮革款：￥80,000+ 金属款：￥20,000+", 80000.0),  # first amount
    ("RMB 18,800~23,000+", 18800.0),
    ("￥ 1,700~5,800+", 1700.0),
    ("", None),
    (None, None),
])
def test_parse_price(text, expected):
    assert _parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("900+", 900),
    ("TB:2W+  JD:1W+", 30000),            # W = 万
    ("TB:800+  JD:500+", 1300),
    ("0", None),
    ("无", None),
    (None, None),
])
def test_parse_sales(text, expected):
    assert _parse_sales(text) == expected


def test_route_cert_splits_fields():
    fire, euro, gb = _route_cert("S2防盗，欧标30分钟防火")
    assert fire and euro                   # both aspects present in one string
    fire, euro, gb = _route_cert("国标耐火测试1H")
    assert fire and gb and not euro
    assert _route_cert("无") == (None, None, None)
    assert _route_cert("无防火防盗认证") == (None, None, None)


@pytest.mark.skipif(not DECK.exists(), reason="deck not present")
def test_parse_real_deck():
    data = parse_deck(DECK)
    assert len(data) >= 8                          # 8 brands with product tables
    assert "德国百卫特 Burg Wächter" in data
    burg = {p["product_name"]: p for p in data["德国百卫特 Burg Wächter"]}
    assert burg["Mango系列-电子锁版"]["price"] == 5780.0
    assert burg["point系列"]["sales_volume"] == 900
    # CL系列 cert routes to both fire + euro
    cl = burg["CL系列"]
    assert cl["fire_rating"] and cl["euro_grade"]
