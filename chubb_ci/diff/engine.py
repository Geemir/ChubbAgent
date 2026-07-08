"""Deterministic snapshot diffing.

Pure functions over :class:`~chubb_ci.schemas.models.ExtractedProduct` lists — no
LLM, no database, no I/O — so behavior is fully testable and reproducible.
"""

from __future__ import annotations

from pydantic import BaseModel

from chubb_ci.diff.matching import normalize_product_key
from chubb_ci.schemas.models import EventType, ExtractedProduct

# Spec fields compared field-by-field; each change emits its own SPEC_CHANGE event.
_SPEC_FIELDS: tuple[str, ...] = (
    "series",
    "category",
    "gb_grade",
    "euro_grade",
    "fire_rating",
    "capacity_l",
    "weight_kg",
    "width_mm",
    "depth_mm",
    "height_mm",
    "lock_type",
    "lead_time_days",
)


class DiffEventData(BaseModel):
    """A single detected change (storage-agnostic; orchestrator persists it)."""

    event_type: EventType
    product_key: str
    product_name: str
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    pct_change: float | None = None
    source_url: str | None = None


def _fmt(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _index(products: list[ExtractedProduct]) -> dict[str, ExtractedProduct]:
    """Index products by normalized key; unnamed products are dropped."""
    out: dict[str, ExtractedProduct] = {}
    for p in products:
        key = normalize_product_key(p.product_name)
        if key:
            out.setdefault(key, p)
    return out


def diff_products(
    previous: list[ExtractedProduct],
    current: list[ExtractedProduct],
    *,
    price_change_min_pct: float = 0.0,
) -> list[DiffEventData]:
    """Compute the change events between two product snapshots.

    Args:
        previous: product set from the prior successful snapshot.
        current: product set from the latest snapshot.
        price_change_min_pct: ignore price moves whose absolute percentage is
            strictly below this threshold (noise filter). ``0`` reports all moves.

    Returns:
        Deterministically ordered list of :class:`DiffEventData`.
    """
    prev = _index(previous)
    curr = _index(current)
    events: list[DiffEventData] = []

    # New products (present now, absent before).
    for key in curr.keys() - prev.keys():
        p = curr[key]
        events.append(
            DiffEventData(
                event_type=EventType.NEW_PRODUCT,
                product_key=key,
                product_name=p.product_name,
                new_value=_fmt(p.price),
                field="price" if p.price is not None else None,
                source_url=p.source_url,
            )
        )

    # Discontinued products (present before, absent now).
    for key in prev.keys() - curr.keys():
        p = prev[key]
        events.append(
            DiffEventData(
                event_type=EventType.DISCONTINUED,
                product_key=key,
                product_name=p.product_name,
                old_value=_fmt(p.price),
                source_url=p.source_url,
            )
        )

    # Changed products (present in both).
    for key in prev.keys() & curr.keys():
        events.extend(_diff_one(key, prev[key], curr[key], price_change_min_pct))

    # Stable ordering: by event type, then product key, then field.
    order = {t: i for i, t in enumerate(EventType)}
    events.sort(key=lambda e: (order[e.event_type], e.product_key, e.field or ""))
    return events


def _diff_one(
    key: str,
    old: ExtractedProduct,
    new: ExtractedProduct,
    price_change_min_pct: float,
) -> list[DiffEventData]:
    events: list[DiffEventData] = []
    name = new.product_name or old.product_name

    # --- Price -----------------------------------------------------------
    if old.price != new.price and (old.price is not None or new.price is not None):
        pct = None
        if old.price not in (None, 0) and new.price is not None:
            pct = round((new.price - old.price) / old.price * 100, 2)
        if pct is None or abs(pct) >= price_change_min_pct:
            events.append(
                DiffEventData(
                    event_type=EventType.PRICE_CHANGE,
                    product_key=key,
                    product_name=name,
                    field="price",
                    old_value=_fmt(old.price),
                    new_value=_fmt(new.price),
                    pct_change=pct,
                    source_url=new.source_url,
                )
            )

    # --- Promotion -------------------------------------------------------
    if (old.promotion or None) != (new.promotion or None):
        events.append(
            DiffEventData(
                event_type=EventType.PROMOTION_CHANGE,
                product_key=key,
                product_name=name,
                field="promotion",
                old_value=old.promotion,
                new_value=new.promotion,
                source_url=new.source_url,
            )
        )

    # --- Availability / stock -------------------------------------------
    if (old.availability or None) != (new.availability or None):
        events.append(
            DiffEventData(
                event_type=EventType.STOCK_CHANGE,
                product_key=key,
                product_name=name,
                field="availability",
                old_value=old.availability,
                new_value=new.availability,
                source_url=new.source_url,
            )
        )

    # --- Scalar spec fields ---------------------------------------------
    for f in _SPEC_FIELDS:
        ov, nv = getattr(old, f), getattr(new, f)
        if (ov or None) != (nv or None):
            events.append(
                DiffEventData(
                    event_type=EventType.SPEC_CHANGE,
                    product_key=key,
                    product_name=name,
                    field=f,
                    old_value=_fmt(ov),
                    new_value=_fmt(nv),
                    source_url=new.source_url,
                )
            )

    # --- Key features (set comparison) ----------------------------------
    old_feats, new_feats = set(old.key_features or []), set(new.key_features or [])
    if old_feats != new_feats:
        events.append(
            DiffEventData(
                event_type=EventType.SPEC_CHANGE,
                product_key=key,
                product_name=name,
                field="key_features",
                old_value="；".join(sorted(old_feats)) or None,
                new_value="；".join(sorted(new_feats)) or None,
                source_url=new.source_url,
            )
        )

    return events
