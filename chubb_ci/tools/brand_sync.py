"""Sync brands.yaml / counterparts.yaml into the database (idempotent upserts)."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlmodel import Session, delete, select

from chubb_ci.config.brands import load_brands, load_counterparts
from chubb_ci.diff.matching import normalize_product_key
from chubb_ci.schemas.models import Brand, CounterpartPair, utcnow


def sync_brands(session: Session, path: str | Path) -> int:
    """Upsert Brand rows from brands.yaml by unique name. Returns brand count."""
    configs = load_brands(path)
    for cfg in configs:
        existing = session.exec(select(Brand).where(Brand.name == cfg.name)).first()
        if existing is None:
            # YAML `focus` is only the initial value; later UI toggles win over re-syncs.
            existing = Brand(name=cfg.name, is_focus=cfg.focus)
            session.add(existing)
        existing.name_en = cfg.name_en
        existing.is_own = cfg.is_own
        existing.positioning = cfg.positioning
        existing.competition_tier = cfg.competition_tier
        existing.target_audience = cfg.target_audience
        existing.strengths = list(cfg.strengths)
        existing.shortcomings = list(cfg.shortcomings)
        existing.price_architecture = [dict(p) for p in cfg.price_architecture]
        existing.market_scale = cfg.market_scale
        existing.supply_chain = cfg.supply_chain
        existing.warranty = cfg.warranty
        existing.updated_at = utcnow()
    session.commit()
    logger.info("synced {} brand profiles from {}", len(configs), Path(path).name)
    return len(configs)


def sync_counterparts(session: Session, path: str | Path) -> int:
    """Replace CounterpartPair rows from counterparts.yaml. Returns pair count."""
    configs = load_counterparts(path)
    session.exec(delete(CounterpartPair))
    for cfg in configs:
        session.add(CounterpartPair(
            own_product_key=normalize_product_key(cfg.own_product),
            comp_company=cfg.comp_company,
            comp_product_key=normalize_product_key(cfg.comp_product),
            note=cfg.note,
        ))
    session.commit()
    logger.info("synced {} counterpart pairs", len(configs))
    return len(configs)
