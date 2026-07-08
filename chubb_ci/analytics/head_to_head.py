"""One-to-one 对标 benchmarking: our model vs its competitor counterpart.

Computes the framework's operational deltas:
    价格差 % | 容积差 % | 周期差 (我司周期 − 竞品周期) | 元/升 & 元/公斤 对比 | 性价比指数
A negative 周期差 is a structural logistics advantage (现货) flagged for channel copy.
"""

from __future__ import annotations

from pydantic import BaseModel

from chubb_ci.normalize import price_per_kg, price_per_l, value_for_money
from chubb_ci.schemas.models import OwnProduct, ProductRecord


class HeadToHead(BaseModel):
    """Computed comparison for one counterpart pair."""

    own_name: str
    own_series: str | None = None
    comp_company: str
    comp_name: str
    own_price: float | None = None
    comp_price: float | None = None
    price_diff_pct: float | None = None      # (own − comp) / comp × 100
    own_capacity_l: float | None = None
    comp_capacity_l: float | None = None
    volume_diff_pct: float | None = None
    own_lead_days: int | None = None
    comp_lead_days: int | None = None
    lead_delta: int | None = None            # 我司 − 竞品；负值 = 我司物流优势
    own_price_per_l: float | None = None
    comp_price_per_l: float | None = None
    own_price_per_kg: float | None = None
    comp_price_per_kg: float | None = None
    vfm_index: float | None = None           # 性价比指数 (comp 元/升 ÷ own 元/升)
    own_security_score: int | None = None
    comp_security_score: int | None = None
    note: str | None = None


def _pct(own: float | None, comp: float | None) -> float | None:
    if own is None or comp is None or comp == 0:
        return None
    return round((own - comp) / comp * 100, 1)


def compare_pair(own: OwnProduct, comp: ProductRecord, note: str | None = None) -> HeadToHead:
    """Compute all deltas for one own↔competitor pair."""
    own_ppl = price_per_l(own.price, own.capacity_l)
    comp_ppl = price_per_l(comp.price, comp.capacity_l)
    lead_delta = None
    if comp.lead_time_days is not None:
        lead_delta = (own.lead_time_days or 0) - comp.lead_time_days

    return HeadToHead(
        own_name=own.product_name,
        own_series=own.series,
        comp_company=comp.company,
        comp_name=comp.product_name,
        own_price=own.price,
        comp_price=comp.price,
        price_diff_pct=_pct(own.price, comp.price),
        own_capacity_l=own.capacity_l,
        comp_capacity_l=comp.capacity_l,
        volume_diff_pct=_pct(own.capacity_l, comp.capacity_l),
        own_lead_days=own.lead_time_days,
        comp_lead_days=comp.lead_time_days,
        lead_delta=lead_delta,
        own_price_per_l=own_ppl,
        comp_price_per_l=comp_ppl,
        own_price_per_kg=price_per_kg(own.price, own.weight_kg),
        comp_price_per_kg=price_per_kg(comp.price, comp.weight_kg),
        vfm_index=value_for_money(comp_ppl, own_ppl),
        own_security_score=own.security_score,
        comp_security_score=comp.security_score,
        note=note,
    )
