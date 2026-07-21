"""Safe serialization and deterministic refresh for product enrichment facts."""

from __future__ import annotations

import json
from typing import Any

from chubb_ci.schemas.models import ProductRecord

ENRICHABLE_PRODUCT_FIELDS = (
    "series", "category", "price", "promotion", "promotion_end_date",
    "launch_date", "availability", "key_features", "gb_grade", "euro_grade",
    "fire_rating", "capacity_l", "weight_kg", "width_mm", "depth_mm",
    "height_mm", "lock_type", "lead_time_days", "sales_volume", "status_label",
    "image_url", "product_url",
)

_FLOAT_FIELDS = {"price", "capacity_l", "weight_kg", "width_mm", "depth_mm", "height_mm"}
_INT_FIELDS = {"lead_time_days", "sales_volume"}
_JSON_FIELDS = {"key_features"}


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def serialize_fact_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def deserialize_fact_value(field: str, value: str) -> Any:
    """Convert a reviewed string fact into the ProductRecord field's native type."""
    if field not in ENRICHABLE_PRODUCT_FIELDS:
        raise ValueError(f"unsupported product field: {field}")
    if field in _FLOAT_FIELDS:
        return float(str(value).replace(",", "").replace("￥", "").replace("¥", "").strip())
    if field in _INT_FIELDS:
        return int(float(str(value).replace(",", "").strip()))
    if field in _JSON_FIELDS:
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError(f"{field} must be a JSON list")
        return [str(item) for item in parsed if str(item).strip()]
    return value.strip()


def refresh_computed_fields(record: ProductRecord) -> None:
    """Recompute derived fields after verified raw facts are applied."""
    from chubb_ci.normalize import fire_hours, security_score, volume_l

    if is_missing(record.capacity_l):
        record.capacity_l = volume_l(record.width_mm, record.depth_mm, record.height_mm)
    if record.fire_rating:
        record.fire_hours = fire_hours(record.fire_rating)
    if record.gb_grade or record.euro_grade:
        record.security_score = security_score(record.gb_grade, record.euro_grade)
