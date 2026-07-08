"""Source definitions: the ``sources.yaml`` schema and loader.

A *source* is one competitor page tracked over time. Adding a competitor means
adding a YAML block — never touching code.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class FetcherKind(StrEnum):
    STATIC = "static"
    BROWSER = "browser"
    LOCAL = "local"


class PageType(StrEnum):
    PRODUCT = "product"
    PRICING = "pricing"
    CAMPAIGN = "campaign"
    NEWS = "news"


class Source(BaseModel):
    """A single monitored competitor page (validated view of a YAML block)."""

    name: str
    company: str
    enabled: bool = True
    fetcher: FetcherKind = FetcherKind.STATIC
    page_type: PageType = PageType.PRODUCT
    channel: str = "官网"
    frequency: str = "daily"
    urls: list[str] = Field(default_factory=list)
    selectors: dict[str, str] = Field(default_factory=dict)
    notes: str = ""

    @field_validator("urls")
    @classmethod
    def _non_empty_urls(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("source must declare at least one url")
        return v

    def is_due(self, frequency_filter: str | None) -> bool:
        """Return True if this source should run for the given cadence.

        ``frequency_filter`` is ``"daily"``/``"weekly"``/None. A source runs on a
        daily pass if its frequency is ``daily`` (weekly sources run only weekly).
        None means "run regardless of cadence" (manual crawl).
        """
        if frequency_filter is None:
            return True
        freq = self.frequency.strip().lower()
        if frequency_filter == "daily":
            return freq == "daily"
        if frequency_filter == "weekly":
            return freq in ("daily", "weekly")
        return True


class SourcesConfig(BaseModel):
    version: int = 1
    defaults: dict = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)


def load_sources(path: str | Path) -> list[Source]:
    """Load and validate sources from a YAML file.

    ``defaults`` are shallow-merged into each source block before validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"sources file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults: dict = raw.get("defaults", {}) or {}
    merged_blocks = []
    for block in raw.get("sources", []) or []:
        merged = {**defaults, **block}
        merged_blocks.append(merged)

    config = SourcesConfig(
        version=raw.get("version", 1),
        defaults=defaults,
        sources=[Source(**b) for b in merged_blocks],
    )
    return config.sources


def enabled_sources(sources: list[Source], frequency_filter: str | None = None) -> list[Source]:
    """Filter to enabled sources due for the given cadence."""
    return [s for s in sources if s.enabled and s.is_due(frequency_filter)]
