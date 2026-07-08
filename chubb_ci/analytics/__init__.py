"""Comparison & opportunity analytics (deterministic, per the business framework)."""

from chubb_ci.analytics.capacity_bands import BAND_DEFS, BandRow, band_matrix
from chubb_ci.analytics.head_to_head import HeadToHead, compare_pair
from chubb_ci.analytics.opportunities import InsightData, detect_opportunities

__all__ = [
    "BAND_DEFS",
    "BandRow",
    "band_matrix",
    "HeadToHead",
    "compare_pair",
    "InsightData",
    "detect_opportunities",
]
