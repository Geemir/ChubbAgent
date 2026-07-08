"""Opportunity & anomaly detection — the framework's three deterministic rules.

1. **pricing_anomaly** — a counterpart pair whose |价格差 %| exceeds the threshold (5%).
2. **market_gap** — a capacity band where competitors field fewer than 3 products.
3. **logistics_advantage** — negative 周期差 (we deliver faster than the counterpart);
   flagged for use in channel promotional copy.
"""

from __future__ import annotations

from pydantic import BaseModel

from chubb_ci.analytics.capacity_bands import BandRow
from chubb_ci.analytics.head_to_head import HeadToHead

PRICE_ANOMALY_THRESHOLD_PCT = 5.0
GAP_THRESHOLD = 3


class InsightData(BaseModel):
    """Storage-agnostic insight; the pipeline persists these as Insight rows."""

    insight_type: str
    severity: str = "Med"
    title: str
    detail: str
    company: str | None = None
    product_key: str | None = None
    payload: dict = {}


def detect_opportunities(
    comparisons: list[HeadToHead],
    bands: list[BandRow],
    *,
    price_threshold_pct: float = PRICE_ANOMALY_THRESHOLD_PCT,
) -> list[InsightData]:
    """Apply the three rules and return the detected insights (deterministic order)."""
    insights: list[InsightData] = []

    # Rule 1 — pricing anomalies on counterpart pairs.
    for c in comparisons:
        if c.price_diff_pct is None or abs(c.price_diff_pct) <= price_threshold_pct:
            continue
        direction = "高于" if c.price_diff_pct > 0 else "低于"
        severity = "High" if abs(c.price_diff_pct) >= 15 else "Med"
        insights.append(InsightData(
            insight_type="pricing_anomaly",
            severity=severity,
            title=f"{c.own_name} 价格{direction}对标竞品 {abs(c.price_diff_pct):.1f}%",
            detail=(
                f"我司 {c.own_name}（¥{c.own_price:,.0f}）对标 {c.comp_company} "
                f"{c.comp_name}（¥{c.comp_price:,.0f}），价格差 {c.price_diff_pct:+.1f}% "
                f"超过 ±{price_threshold_pct:.0f}% 阈值，建议复核定价策略。"
            ),
            company=c.comp_company,
            payload={"price_diff_pct": c.price_diff_pct, "own": c.own_name,
                     "comp": c.comp_name, "vfm_index": c.vfm_index},
        ))

    # Rule 2 — capacity-band market gaps.
    for b in bands:
        if not b.is_gap:
            continue
        insights.append(InsightData(
            insight_type="market_gap",
            severity="Med",
            title=f"容量段「{b.label}」竞品仅 {b.comp_count} 款 — 市场空档",
            detail=(
                f"{b.label} 容量段竞品在售仅 {b.comp_count} 款（阈值 {GAP_THRESHOLD}），"
                f"我司在售 {b.own_count} 款。竞争密度低，"
                + ("可考虑补充产品线抢占空档。" if b.own_count == 0
                   else "我司已有布局，可加大该段位推广。")
            ),
            payload={"band": b.label, "comp_count": b.comp_count, "own_count": b.own_count},
        ))

    # Rule 3 — logistics advantages (negative 周期差).
    for c in comparisons:
        if c.lead_delta is None or c.lead_delta >= 0:
            continue
        insights.append(InsightData(
            insight_type="logistics_advantage",
            severity="Med",
            title=f"{c.own_name} 交付快 {-c.lead_delta} 天（vs {c.comp_company}）",
            detail=(
                f"我司 {c.own_name} 订货周期 {c.own_lead_days} 天（现货），"
                f"{c.comp_company} {c.comp_name} 需 {c.comp_lead_days} 天。"
                f"周期差 {c.lead_delta} 天为结构性物流优势，建议用于渠道推广文案。"
            ),
            company=c.comp_company,
            payload={"lead_delta": c.lead_delta, "own": c.own_name, "comp": c.comp_name},
        ))

    return insights
