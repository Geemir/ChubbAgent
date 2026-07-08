"""Loaders for brand profiles (brands.yaml) and 对标 pairs (counterparts.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class BrandConfig(BaseModel):
    """Validated view of one brands.yaml block (mirrors the Brand table)."""

    name: str
    name_en: str | None = None
    is_own: bool = False
    focus: bool = False   # 重点关注竞品
    positioning: str | None = None
    competition_tier: str | None = None
    target_audience: str | None = None
    strengths: list[str] = Field(default_factory=list)
    shortcomings: list[str] = Field(default_factory=list)
    price_architecture: list[dict] = Field(default_factory=list)
    market_scale: str | None = None
    supply_chain: str | None = None
    warranty: str | None = None


class CounterpartConfig(BaseModel):
    """One 对标 pair: our model name ↔ competitor company + product name."""

    own_product: str
    comp_company: str
    comp_product: str
    note: str | None = None


def load_brands(path: str | Path) -> list[BrandConfig]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"brands file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [BrandConfig(**b) for b in raw.get("brands", []) or []]


def load_counterparts(path: str | Path) -> list[CounterpartConfig]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [CounterpartConfig(**c) for c in raw.get("pairs", []) or []]
