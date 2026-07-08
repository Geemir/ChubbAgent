"""Deterministic diff engine: compare product snapshots without an LLM."""

from chubb_ci.diff.engine import DiffEventData, diff_products
from chubb_ci.diff.matching import normalize_product_key

__all__ = ["DiffEventData", "diff_products", "normalize_product_key"]
