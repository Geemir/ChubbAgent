"""Tests for the deterministic diff engine — the pipeline's core logic."""

from __future__ import annotations

from chubb_ci.diff.engine import diff_products
from chubb_ci.schemas.models import EventType, ExtractedProduct


def P(name: str, **kw) -> ExtractedProduct:
    return ExtractedProduct(product_name=name, **kw)


def _types(events) -> set[str]:
    return {e.event_type.value for e in events}


def test_no_change_yields_no_events():
    prev = [P("A系列", price=1000), P("B系列", price=2000)]
    assert diff_products(prev, list(prev)) == []


def test_new_product_detected():
    prev = [P("A系列", price=1000)]
    curr = [P("A系列", price=1000), P("B系列", price=2000)]
    events = diff_products(prev, curr)
    assert len(events) == 1
    e = events[0]
    assert e.event_type is EventType.NEW_PRODUCT
    assert e.product_name == "B系列"
    assert e.new_value == "2000"


def test_discontinued_detected():
    prev = [P("A系列", price=1000), P("B系列", price=2000)]
    curr = [P("A系列", price=1000)]
    events = diff_products(prev, curr)
    assert [e.event_type for e in events] == [EventType.DISCONTINUED]
    assert events[0].product_name == "B系列"


def test_price_change_with_pct():
    prev = [P("A系列", price=1000)]
    curr = [P("A系列", price=800)]
    events = diff_products(prev, curr)
    assert len(events) == 1
    e = events[0]
    assert e.event_type is EventType.PRICE_CHANGE
    assert e.old_value == "1000" and e.new_value == "800"
    assert e.pct_change == -20.0


def test_price_change_threshold_filters_small_moves():
    prev = [P("A系列", price=1000)]
    curr = [P("A系列", price=995)]  # -0.5%
    assert diff_products(prev, curr, price_change_min_pct=1.0) == []
    assert len(diff_products(prev, curr, price_change_min_pct=0.0)) == 1


def test_promotion_and_stock_changes():
    prev = [P("A系列", price=1000, promotion=None, availability="有货")]
    curr = [P("A系列", price=1000, promotion="618直降200", availability="预售")]
    events = diff_products(prev, curr)
    assert _types(events) == {
        EventType.PROMOTION_CHANGE.value,
        EventType.STOCK_CHANGE.value,
    }


def test_spec_change_per_field_and_features():
    prev = [P("A系列", price=1000, gb_grade="A", key_features=["防撬"])]
    curr = [P("A系列", price=1000, gb_grade="B", key_features=["防撬", "指纹"])]
    events = diff_products(prev, curr)
    spec = [e for e in events if e.event_type is EventType.SPEC_CHANGE]
    fields = {e.field for e in spec}
    assert "gb_grade" in fields and "key_features" in fields


def test_name_normalization_matches_across_punctuation():
    # Same product, different surrounding punctuation/spacing/full-width.
    prev = [P("摩根系列 （标准版）", price=5000)]
    curr = [P("摩根系列(标准版)", price=4500)]
    events = diff_products(prev, curr)
    assert [e.event_type for e in events] == [EventType.PRICE_CHANGE]


def test_ordering_is_deterministic():
    prev = [P("Z", price=1), P("Y", price=1)]
    curr = [P("Z", price=2), P("Y", price=2), P("X", price=9)]
    e1 = diff_products(prev, curr)
    e2 = diff_products(list(reversed(prev)), list(reversed(curr)))
    assert [(e.event_type, e.product_key) for e in e1] == [
        (e.event_type, e.product_key) for e in e2
    ]


def test_unnamed_products_ignored():
    prev = [P("")]
    curr = [P(""), P("A系列", price=100)]
    events = diff_products(prev, curr)
    assert [e.event_type for e in events] == [EventType.NEW_PRODUCT]
