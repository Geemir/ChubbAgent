"""Deterministic standardization engine (per the business analysis framework).

Converts free-text ratings and raw dimensions into comparable numeric metrics.
Pure functions only — no LLM, no I/O — mirroring `chubb_ci/diff/matching.py`.
"""

from chubb_ci.normalize.metrics import (
    price_per_fire_hour,
    price_per_kg,
    price_per_l,
    value_for_money,
    value_index,
    volume_l,
)
from chubb_ci.normalize.ratings import fire_hours, security_score

__all__ = [
    "fire_hours",
    "security_score",
    "volume_l",
    "price_per_l",
    "price_per_kg",
    "price_per_fire_hour",
    "value_index",
    "value_for_money",
]
