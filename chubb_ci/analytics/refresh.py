"""Compute comparisons/bands/insights from current DB state and persist insights.

Shared by the pipeline (after each crawl), the seeder, and the dashboard service.
"""

from __future__ import annotations

from loguru import logger

from chubb_ci.analytics.capacity_bands import BandRow, band_matrix
from chubb_ci.analytics.head_to_head import HeadToHead, compare_pair
from chubb_ci.analytics.opportunities import detect_opportunities
from chubb_ci.schemas.models import Insight, OwnProduct, ProductRecord
from chubb_ci.storage.repositories import Repository


def latest_per_product(products: list[ProductRecord]) -> dict[tuple[str, str], ProductRecord]:
    """Latest record per (company, product_key)."""
    latest: dict[tuple[str, str], ProductRecord] = {}
    for p in products:
        key = (p.company, p.product_key)
        cur = latest.get(key)
        if cur is None or (p.crawl_time and cur.crawl_time and p.crawl_time >= cur.crawl_time):
            latest[key] = p
    return latest


def build_comparisons(
    repo: Repository,
) -> tuple[list[HeadToHead], list[BandRow], list[OwnProduct], list[ProductRecord]]:
    """Assemble head-to-head comparisons + capacity-band matrix from the DB."""
    own = repo.own_products()
    own_map = {p.product_key: p for p in own}
    latest = latest_per_product(repo.all_products())
    comp_list = list(latest.values())

    comparisons: list[HeadToHead] = []
    for pair in repo.counterpart_pairs():
        own_p = own_map.get(pair.own_product_key)
        comp_p = latest.get((pair.comp_company, pair.comp_product_key))
        if own_p is None or comp_p is None:
            continue  # counterpart not (yet) present in data
        comparisons.append(compare_pair(own_p, comp_p, note=pair.note))

    bands = band_matrix(comp_list, own)
    return comparisons, bands, own, comp_list


def refresh_insights(repo: Repository, run_id: int | None = None) -> list[Insight]:
    """Recompute all insights from current state and replace the Insight table."""
    comparisons, bands, own, _ = build_comparisons(repo)
    if not own:
        logger.info("no own catalog imported; skipping insight refresh")
        return []
    detected = detect_opportunities(comparisons, bands)
    rows = [
        Insight(
            run_id=run_id,
            insight_type=d.insight_type,
            severity=d.severity,
            title=d.title,
            detail=d.detail,
            company=d.company,
            product_key=d.product_key,
            payload=dict(d.payload),
        )
        for d in detected
    ]
    repo.replace_insights(rows)
    logger.info("insights refreshed: {} detected", len(rows))
    return rows
