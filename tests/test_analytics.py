"""Tests for the comparison & opportunity analytics (chubb_ci/analytics)."""

from __future__ import annotations

from chubb_ci.analytics.capacity_bands import band_label, band_matrix
from chubb_ci.analytics.head_to_head import compare_pair
from chubb_ci.analytics.opportunities import detect_opportunities
from chubb_ci.schemas.models import OwnProduct, ProductRecord


def OWN(**kw) -> OwnProduct:
    base = dict(product_name="集宝 测试款", product_key="k", price=12000.0,
                capacity_l=80.0, weight_kg=50.0, lead_time_days=0, security_score=4)
    base.update(kw)
    return OwnProduct(**base)


def COMP(**kw) -> ProductRecord:
    base = dict(company="竞品公司", product_name="竞品款", product_key="c",
                price=10000.0, capacity_l=75.0, weight_kg=60.0, lead_time_days=15)
    base.update(kw)
    return ProductRecord(**base)


# ---------------------------------------------------------------- head-to-head
def test_compare_pair_deltas():
    h = compare_pair(OWN(), COMP())
    assert h.price_diff_pct == 20.0                # (12000-10000)/10000
    assert h.volume_diff_pct == 6.7                # (80-75)/75
    assert h.lead_delta == -15                     # 0 - 15 → our advantage
    assert h.own_price_per_l == 150.0
    assert h.comp_price_per_l == 133.3
    # vfm = comp 元/升 ÷ own 元/升 < 1 → competitor is cheaper per liter
    assert h.vfm_index < 1


def test_compare_pair_handles_missing_data():
    h = compare_pair(OWN(price=None), COMP(lead_time_days=None, capacity_l=None))
    assert h.price_diff_pct is None
    assert h.volume_diff_pct is None
    assert h.lead_delta is None
    assert h.vfm_index is None


# ---------------------------------------------------------------- capacity bands
def test_band_label_brackets():
    assert band_label(20) == "小型 ≤30L"
    assert band_label(30) == "小型 ≤30L"        # inclusive upper bound
    assert band_label(31) == "中型 30-60L"
    assert band_label(80) == "中大型 60-100L"
    assert band_label(150) == "大型 100-200L"
    assert band_label(500) == "超大型 >200L"
    assert band_label(None) is None
    assert band_label(0) is None


def test_band_matrix_stats_and_gap():
    comps = [COMP(capacity_l=20, price=1000), COMP(capacity_l=25, price=2000),
             COMP(capacity_l=28, price=3000), COMP(capacity_l=80, price=5000)]
    owns = [OWN(capacity_l=22, price=2400)]
    rows = band_matrix(comps, owns, gap_threshold=3)
    small = next(r for r in rows if r.label == "小型 ≤30L")
    assert small.comp_count == 3 and small.comp_avg == 2000
    assert small.comp_min == 1000 and small.comp_max == 3000
    assert small.own_avg == 2400 and small.premium_pct == 20.0
    assert not small.is_gap                       # 3 competitors = not a gap (< threshold)
    mid_large = next(r for r in rows if r.label == "中大型 60-100L")
    assert mid_large.comp_count == 1 and mid_large.is_gap


# ---------------------------------------------------------------- opportunities
def test_detect_all_three_rules():
    h = compare_pair(OWN(), COMP())               # +20% price, -15d lead
    # Enough competitor capacity data to judge gaps: 3 in the small band, none elsewhere.
    comps = [COMP(capacity_l=15, price=800), COMP(capacity_l=20, price=900),
             COMP(capacity_l=25, price=1000)]
    bands = band_matrix(comps, [OWN(capacity_l=80)], gap_threshold=3)
    insights = detect_opportunities([h], bands)
    types = {i.insight_type for i in insights}
    assert "pricing_anomaly" in types             # |20%| > 5%
    assert "market_gap" in types                  # 60-100L band has 0 competitors
    assert "logistics_advantage" in types         # lead_delta = -15


def test_market_gap_suppressed_when_no_competitor_capacity():
    # Competitors with unknown volume don't fall into bands → no false gaps.
    bands = band_matrix([COMP(capacity_l=None, price=5000)], [OWN(capacity_l=80)])
    insights = detect_opportunities([], bands)
    assert all(i.insight_type != "market_gap" for i in insights)


def test_no_anomaly_within_threshold():
    h = compare_pair(OWN(price=10300.0), COMP())  # +3% → within ±5%
    insights = detect_opportunities([h], [])
    assert all(i.insight_type != "pricing_anomaly" for i in insights)


def test_severity_escalates_on_large_gap():
    h = compare_pair(OWN(price=13000.0), COMP())  # +30%
    insights = detect_opportunities([h], [])
    anomaly = next(i for i in insights if i.insight_type == "pricing_anomaly")
    assert anomaly.severity == "High"
