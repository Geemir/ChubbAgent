"""Derivative metric math: volumes, unit costs, and composite indexes.

Definitions follow AnalyzeInformation.md §2–3:

* volume (容积, L) is computed from **internal** W×D×H in millimetres
* 元/升 = price ÷ volume; 元/公斤 = price ÷ net weight; 元/小时防火 = price ÷ fire hours
* 综合指数 (value index): benchmark unit-price ÷ product unit-price — **> 1.1** means the
  product is cheaper per unit than its capacity-band benchmark ("truly cost-effective"),
  **< 0.9** flags repricing / cost optimization
* 性价比指数 (value-for-money): competitor metric ÷ our metric
"""

from __future__ import annotations

VALUE_INDEX_STRONG = 1.1   # > 1.1  → 高性价比 (truly cost-effective)
VALUE_INDEX_WEAK = 0.9     # < 0.9  → 需重新定价/降本


def volume_l(width_mm: float | None, depth_mm: float | None, height_mm: float | None) -> float | None:
    """Internal W×D×H (mm) → volume in liters, rounded to 1 decimal."""
    if not width_mm or not depth_mm or not height_mm:
        return None
    if width_mm <= 0 or depth_mm <= 0 or height_mm <= 0:
        return None
    return round(width_mm * depth_mm * height_mm / 1_000_000.0, 1)


def _safe_div(price: float | None, denom: float | None) -> float | None:
    if price is None or denom is None or denom <= 0 or price < 0:
        return None
    return round(price / denom, 1)


def price_per_l(price: float | None, volume: float | None) -> float | None:
    """元/升容量 — spatial cost-efficiency."""
    return _safe_div(price, volume)


def price_per_kg(price: float | None, weight_kg: float | None) -> float | None:
    """元/公斤重量 — material cost-efficiency."""
    return _safe_div(price, weight_kg)


def price_per_fire_hour(price: float | None, fire_hours: float | None) -> float | None:
    """元/小时防火 — safety-premium cost-efficiency."""
    return _safe_div(price, fire_hours)


def value_index(product_unit_price: float | None, benchmark_unit_price: float | None) -> float | None:
    """综合指数 = benchmark unit-price ÷ product unit-price.

    Higher = the product delivers the same unit (liter/kg/hour) for less money than the
    benchmark (e.g. its capacity-band average). > 1.1 is pitch-worthy, < 0.9 needs action.
    """
    if not product_unit_price or not benchmark_unit_price:
        return None
    if product_unit_price <= 0 or benchmark_unit_price <= 0:
        return None
    return round(benchmark_unit_price / product_unit_price, 2)


def value_for_money(competitor_metric: float | None, own_metric: float | None) -> float | None:
    """性价比指数 = competitor metric ÷ our metric (empirical negotiation leverage).

    Applied to a *cost* metric such as 元/升: > 1 means the competitor pays more per unit
    than we do — i.e. our product is the better value.
    """
    if not competitor_metric or not own_metric:
        return None
    if own_metric <= 0 or competitor_metric <= 0:
        return None
    return round(competitor_metric / own_metric, 2)
