"""容量段价格带分布 — capacity-band price aggregation matrix.

Standardized volumetric brackets per the framework:
    小型 ≤30L → 中型 30–60L → 中大型 60–100L → 大型 100–200L → 超大型 >200L
Per band: competitor avg/min/max price + sample count vs our avg price + premium %.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

# (lower bound exclusive except first, upper bound inclusive, label)
BAND_DEFS: list[tuple[float, float, str]] = [
    (0.0, 30.0, "小型 ≤30L"),
    (30.0, 60.0, "中型 30-60L"),
    (60.0, 100.0, "中大型 60-100L"),
    (100.0, 200.0, "大型 100-200L"),
    (200.0, math.inf, "超大型 >200L"),
]


class BandRow(BaseModel):
    label: str
    low: float
    high: float
    comp_count: int = 0
    comp_avg: float | None = None
    comp_min: float | None = None
    comp_max: float | None = None
    own_count: int = 0
    own_avg: float | None = None
    premium_pct: float | None = None   # (own_avg − comp_avg) / comp_avg × 100
    is_gap: bool = False               # competitor count < gap threshold


def band_label(capacity_l: float | None) -> str | None:
    if capacity_l is None or capacity_l <= 0:
        return None
    for low, high, label in BAND_DEFS:
        if low < capacity_l <= high or (low == 0.0 and capacity_l <= high):
            return label
    return None


def _stats(prices: list[float]) -> tuple[float | None, float | None, float | None]:
    if not prices:
        return None, None, None
    return round(sum(prices) / len(prices), 0), min(prices), max(prices)


def band_matrix(
    comp_products: list,
    own_products: list,
    *,
    gap_threshold: int = 3,
) -> list[BandRow]:
    """Build the capacity-band matrix from priced products with known volume.

    ``comp_products`` / ``own_products`` need only ``capacity_l`` and ``price`` attributes.
    """
    rows: list[BandRow] = []
    for low, high, label in BAND_DEFS:
        comp_prices = [
            p.price for p in comp_products
            if p.price and p.capacity_l and band_label(p.capacity_l) == label
        ]
        own_prices = [
            p.price for p in own_products
            if p.price and p.capacity_l and band_label(p.capacity_l) == label
        ]
        c_avg, c_min, c_max = _stats(comp_prices)
        o_avg, _, _ = _stats(own_prices)
        premium = None
        if c_avg and o_avg:
            premium = round((o_avg - c_avg) / c_avg * 100, 1)
        rows.append(BandRow(
            label=label, low=low, high=high if high != math.inf else 1e9,
            comp_count=len(comp_prices), comp_avg=c_avg, comp_min=c_min, comp_max=c_max,
            own_count=len(own_prices), own_avg=o_avg, premium_pct=premium,
            is_gap=len(comp_prices) < gap_threshold,
        ))
    return rows
