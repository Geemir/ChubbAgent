"""Build an all-REAL dataset — no fabricated competitors.

Real sources, in order:
1. brand profiles (config/brands.yaml) + 对标 pairs (config/counterparts.yaml)
2. 集宝 own catalog (ChubbProductsList.xlsx)
3. competitor product tables from the marketing deck (CompetitorAnalysisV7.pptx) —
   8 brands, real prices/sales/certs
4. live crawl of every enabled real source (官网 + 苏宁 marketplace search); the
   ``frequency: manual`` offline-demo fixture is excluded by using the weekly cadence
5. deterministic insight recompute

Unlike ``seed-demo`` this never invents products. Use it for the real dashboard.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from chubb_ci.analytics.refresh import refresh_insights
from chubb_ci.config.settings import Settings, get_settings
from chubb_ci.storage.db import get_engine, init_db, session_scope
from chubb_ci.storage.repositories import Repository

_ROOT = Path(__file__).resolve().parents[2]


def _reset(settings: Settings) -> None:
    from sqlmodel import SQLModel

    engine = get_engine(settings)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def load_real(settings: Settings | None = None, *, crawl: bool = True) -> dict:
    settings = settings or get_settings()
    settings.ensure_dirs()
    init_db(settings)
    _reset(settings)

    from chubb_ci.tools.brand_sync import sync_brands, sync_counterparts
    from chubb_ci.tools.catalog_import import import_catalog
    from chubb_ci.tools.pptx_ingest import ingest_pptx

    cfg = _ROOT / "config"
    catalog = _ROOT / "ChubbProductsList.xlsx"
    deck = _ROOT / "CompetitorAnalysisV7.pptx"

    with session_scope(settings) as session:
        n_brands = sync_brands(session, cfg / "brands.yaml")
        n_pairs = sync_counterparts(session, cfg / "counterparts.yaml")
        n_own = import_catalog(session, catalog) if catalog.exists() else 0
        n_deck = ingest_pptx(session, deck)["products"] if deck.exists() else 0

    crawled = {"sources_ok": 0, "products": 0}
    if crawl:
        from chubb_ci.pipeline import run_crawl

        # "weekly" cadence covers all real daily+weekly sources but skips the
        # frequency=manual offline-demo fixture (keeps fabricated data out).
        summary = run_crawl(settings, kind="real", frequency_filter="weekly")
        crawled = {"sources_ok": summary.sources_ok, "products": summary.products_extracted}

    with session_scope(settings) as session:
        insights = refresh_insights(Repository(session))
        products = len(Repository(session).all_products())

    result = {
        "brands": n_brands, "pairs": n_pairs, "own_products": n_own,
        "deck_products": n_deck, "crawled_ok": crawled["sources_ok"],
        "crawled_products": crawled["products"], "total_products": products,
        "insights": len(insights),
    }
    logger.info("loaded REAL dataset: {}", result)
    return result
