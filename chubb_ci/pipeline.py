"""End-to-end pipeline: fetch → extract → diff → store → report → export.

This module is the single orchestration point shared by the CLI and the scheduler.
Each source is processed independently; one failing source never aborts the run.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone

from loguru import logger
from pydantic import BaseModel

from chubb_ci.config.settings import Settings, get_settings
from chubb_ci.config.sources import FetcherKind, Source, enabled_sources, load_sources
from chubb_ci.crawler.orchestrator import fetch_and_clean, make_fetcher
from chubb_ci.diff.engine import DiffEventData, diff_products
from chubb_ci.extractor.extractor import extract_products
from chubb_ci.llm.base import LLMClient
from chubb_ci.llm.factory import build_llm, resolve_model
from chubb_ci.schemas.models import (
    DiffEvent,
    ExtractedProduct,
    ProductRecord,
    Report,
    ReportType,
    Snapshot,
    SnapshotStatus,
    record_to_extracted,
)
from chubb_ci.sinks.excel_sink import ExcelSink
from chubb_ci.storage.db import init_db, session_scope
from chubb_ci.storage.repositories import Repository
from chubb_ci.summary.daily import build_daily_report
from chubb_ci.summary.facts import ReportDraft
from chubb_ci.summary.weekly import build_weekly_report


class CrawlSummary(BaseModel):
    run_id: int
    kind: str
    sources_ok: int = 0
    sources_failed: int = 0
    sources_blocked: int = 0
    sources_skipped: int = 0
    baselines: int = 0          # first-time captures (no prior snapshot to diff against)
    products_extracted: int = 0
    events_detected: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_cny: float = 0.0


# =========================================================================
# Helpers
# =========================================================================
def _to_record(
    p: ExtractedProduct, *, snapshot_id: int, run_id: int, source: Source
) -> ProductRecord:
    from chubb_ci.diff.matching import model_code
    from chubb_ci.normalize import fire_hours, security_score, volume_l

    # Deterministic standardization at ingest (never computed by the LLM).
    capacity = p.capacity_l or volume_l(p.width_mm, p.depth_mm, p.height_mm)
    return ProductRecord(
        snapshot_id=snapshot_id,
        run_id=run_id,
        source_name=source.name,
        company=source.company,
        channel=source.channel,
        product_name=p.product_name,
        product_key=p.product_key(),
        model_code=model_code(p.product_name),
        series=p.series,
        category=p.category,
        price=p.price,
        currency=p.currency,
        promotion=p.promotion,
        promotion_end_date=p.promotion_end_date,
        launch_date=p.launch_date,
        availability=p.availability,
        key_features=list(p.key_features or []),
        gb_grade=p.gb_grade,
        euro_grade=p.euro_grade,
        fire_rating=p.fire_rating,
        capacity_l=capacity,
        weight_kg=p.weight_kg,
        width_mm=p.width_mm,
        depth_mm=p.depth_mm,
        height_mm=p.height_mm,
        lock_type=p.lock_type,
        lead_time_days=p.lead_time_days,
        sales_volume=p.sales_volume,
        status_label=p.status_label,
        image_url=p.image_url,
        product_url=p.product_url,
        source_url=p.source_url,
        fire_hours=fire_hours(p.fire_rating),
        security_score=security_score(p.gb_grade, p.euro_grade),
    )


def _tile_to_product(tile, page_url: str) -> ExtractedProduct:
    """Marketplace tile → ExtractedProduct (name/price/image/url/sales)."""
    return ExtractedProduct(
        product_name=tile.name, category="保险柜", price=tile.price, currency="CNY",
        sales_volume=tile.sales_volume, image_url=tile.image_url,
        product_url=tile.product_url, source_url=page_url,
    )


def _enrich_details(
    settings: Settings, source: Source, products: list[ExtractedProduct], summary
) -> None:
    """Fetch a bounded number of detail pages and fill missing specs on those products."""
    from chubb_ci.crawler.detail import extract_specs

    n_max = settings.detail_enrich_max
    if n_max <= 0:
        return
    # Enrich the priciest / highest-sales products first (most decision-relevant).
    candidates = [p for p in products if p.product_url and p.capacity_l is None]
    candidates.sort(key=lambda p: (p.sales_volume or 0, p.price or 0), reverse=True)
    if not candidates:
        return

    fetcher = make_fetcher(source, settings)
    enriched = 0
    for p in candidates[:n_max]:
        try:
            res = fetcher.fetch(p.product_url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("detail fetch failed {}: {}", p.product_url, exc)
            continue
        if not res.ok or not res.html:
            continue
        specs = extract_specs(res.html)
        for field, value in specs.items():
            if getattr(p, field, None) is None:
                setattr(p, field, value)
        if specs:
            enriched += 1
    if enriched:
        logger.info("detail enrichment: filled specs on {} products for {}",
                    enriched, source.name)


def _name_from_detail(html: str) -> str:
    """Fallback product name from a detail page's <h1>/<title> when the listing had none."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    for sel in ("h1", ".product-title", ".pro-title", ".title"):
        n = tree.css_first(sel)
        if n and len(n.text(strip=True)) >= 3:
            return n.text(strip=True)[:120]
    t = tree.css_first("title")
    if t:  # drop the "… | 品牌" site suffix
        return re.split(r"[|｜\-–—]", t.text(strip=True))[0].strip()[:120]
    return ""


def _crawl_catalog_page(
    settings: Settings, source: Source, url: str, html: str
) -> list[ExtractedProduct]:
    """Spider one 官网 listing/category page → every product (name/image/specs).

    ``selectors.product_href`` (regex) marks detail links. When ``enrich_details`` is set,
    each detail page is fetched and its spec table parsed (dims/weight/certs); otherwise
    we keep just the name + official image from the listing (JS sites with AJAX specs).
    """
    from chubb_ci.crawler.catalog import parse_catalog_entries
    from chubb_ci.crawler.detail import extract_main_image, extract_specs

    sel = source.selectors or {}
    href = sel.get("product_href")
    if not href:
        logger.warning("catalog source {} missing selectors.product_href; skipping", source.name)
        return []

    res = parse_catalog_entries(
        html, url, product_href=href, name_sel=sel.get("name"), image_sel=sel.get("image"))
    entries = res.entries[: max(1, source.catalog_max_pages)]
    if not entries:
        return []

    fetcher = make_fetcher(source, settings) if source.enrich_details else None
    delay = max(0.0, settings.rate_limit_delay) if source.fetcher is FetcherKind.BROWSER else 0.0
    products: list[ExtractedProduct] = []
    enriched = 0
    for i, e in enumerate(entries):
        name, specs, image = e.name, {}, e.image_url
        if fetcher is not None:
            if i and delay:
                time.sleep(delay)  # polite spacing between detail fetches
            try:
                d = fetcher.fetch(e.url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("catalog detail fetch failed {}: {}", e.url, exc)
                d = None
            if d and d.ok and d.html:
                specs = extract_specs(d.html)
                if specs:
                    enriched += 1
                if not name:
                    name = _name_from_detail(d.html)
                if not image:  # grab the official product image from the detail page
                    image = extract_main_image(d.html, e.url)
        if not name:
            continue
        products.append(ExtractedProduct(
            product_name=name, category="保险柜",
            image_url=image, product_url=e.url, source_url=url, **specs,
        ))
    logger.info("catalog spider: {} products ({} spec-enriched) for {} {}",
                len(products), enriched, source.name, url)
    return products


def _events_to_rows(
    events: list[DiffEventData], *, run_id: int, source: Source
) -> list[DiffEvent]:
    return [
        DiffEvent(
            run_id=run_id,
            source_name=source.name,
            company=source.company,
            event_type=e.event_type.value,
            product_key=e.product_key,
            product_name=e.product_name,
            field=e.field,
            old_value=e.old_value,
            new_value=e.new_value,
            pct_change=e.pct_change,
            channel=source.channel,
            source_url=e.source_url,
        )
        for e in events
    ]


def _estimate_cost(settings: Settings, tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in / 1_000_000 * settings.llm_price_input_per_m
        + tokens_out / 1_000_000 * settings.llm_price_output_per_m,
        4,
    )


# =========================================================================
# Crawl
# =========================================================================
def run_crawl(
    settings: Settings | None = None,
    *,
    kind: str = "manual",
    frequency_filter: str | None = None,
    llm: LLMClient | None = None,
    override_urls: dict[str, str] | None = None,
    only_names: list[str] | None = None,
) -> CrawlSummary:
    """Fetch + extract + diff all due sources; persist snapshots, products, events.

    ``only_names`` crawls exactly those source names (bypassing enabled/cadence filters);
    used by the offline demo to run a disabled fixture source.
    """
    settings = settings or get_settings()
    init_db(settings)
    llm = llm or build_llm(settings)
    extract_model = resolve_model(settings, "extract")
    domain_context = settings.load_domain_context()
    override_urls = override_urls or {}

    all_sources = load_sources(settings.sources_path)
    if only_names:
        sources = [s for s in all_sources if s.name in only_names]
    else:
        sources = enabled_sources(all_sources, frequency_filter)
    logger.info("crawl kind={} sources={}", kind, [s.name for s in sources])

    with session_scope(settings) as session:
        repo = Repository(session)
        run = repo.create_run(kind)
        summary = CrawlSummary(run_id=run.id, kind=kind)

        # Marketplaces (JD especially) rate-limit by IP; back-to-back requests trip
        # "访问频率过高". Space out browser fetches by rate_limit_delay to stay polite.
        browser_delay = max(0.0, settings.rate_limit_delay)
        first = True
        for source in sources:
            for raw_url in source.urls:
                url = override_urls.get(raw_url, raw_url)
                if not first and source.fetcher is FetcherKind.BROWSER and browser_delay:
                    time.sleep(browser_delay)
                first = False
                try:
                    _process_url(settings, repo, run.id, source, url, llm, extract_model,
                                 domain_context, summary)
                except Exception as exc:  # noqa: BLE001 - isolate per-URL failures
                    logger.exception("unhandled error for {} {}: {}", source.name, url, exc)
                    summary.sources_failed += 1
                    repo.add_snapshot(Snapshot(
                        run_id=run.id, source_name=source.name, company=source.company,
                        url=url, page_type=source.page_type.value, channel=source.channel,
                        status=SnapshotStatus.ERROR.value, error=str(exc),
                    ))

        # finalize run bookkeeping
        run.sources_ok = summary.sources_ok
        run.sources_failed = summary.sources_failed
        run.sources_blocked = summary.sources_blocked
        run.sources_skipped = summary.sources_skipped
        run.baselines = summary.baselines
        run.products_extracted = summary.products_extracted
        run.events_detected = summary.events_detected
        run.tokens_in = summary.tokens_in
        run.tokens_out = summary.tokens_out
        run.est_cost_cny = _estimate_cost(settings, summary.tokens_in, summary.tokens_out)
        summary.est_cost_cny = run.est_cost_cny
        repo.finish_run(run, status="ok")

        # Recompute market insights (对标/机会) from the fresh state.
        from chubb_ci.analytics.refresh import refresh_insights

        refresh_insights(repo, run_id=run.id)

    logger.info(
        "crawl done: ok={} baselines={} blocked={} error={} skipped={} products={} "
        "changes={} cost≈¥{}",
        summary.sources_ok, summary.baselines, summary.sources_blocked,
        summary.sources_failed, summary.sources_skipped, summary.products_extracted,
        summary.events_detected, summary.est_cost_cny,
    )
    return summary


def _process_url(
    settings: Settings,
    repo: Repository,
    run_id: int,
    source: Source,
    url: str,
    llm: LLMClient,
    extract_model: str,
    domain_context: str,
    summary: CrawlSummary,
) -> None:
    fetcher = make_fetcher(source, settings)
    cleaned = fetch_and_clean(fetcher, url, settings)

    # --- fetch failure / blocked ---------------------------------------
    if not cleaned.fetch.ok:
        if cleaned.fetch.blocked:
            status = SnapshotStatus.BLOCKED
            summary.sources_blocked += 1
            logger.warning("BLOCKED (anti-bot) {} {}", source.name, url)
        else:
            status = SnapshotStatus.ERROR
            summary.sources_failed += 1
            logger.warning("FETCH ERROR {} {}: {}", source.name, url, cleaned.fetch.error)
        repo.add_snapshot(Snapshot(
            run_id=run_id, source_name=source.name, company=source.company, url=url,
            page_type=source.page_type.value, channel=source.channel,
            status=status.value, error=cleaned.fetch.error,
        ))
        return

    # --- unchanged since last crawl → skip extraction ------------------
    prev = repo.last_snapshot(source.name)
    if prev and prev.content_hash and prev.content_hash == cleaned.content_hash:
        summary.sources_skipped += 1
        repo.add_snapshot(Snapshot(
            run_id=run_id, source_name=source.name, company=source.company, url=url,
            page_type=source.page_type.value, channel=source.channel,
            content_hash=cleaned.content_hash, status=SnapshotStatus.SKIPPED.value,
        ))
        logger.info("unchanged, skipped extraction: {} {}", source.name, url)
        return

    # --- persist raw html ----------------------------------------------
    raw_path = None
    if cleaned.fetch.html:
        settings.ensure_dirs()
        raw_file = settings.raw_path / f"{source.name}_{datetime.now():%Y%m%d_%H%M%S}.html"
        raw_file.write_text(cleaned.fetch.html, encoding="utf-8")
        raw_path = str(raw_file)

    # --- extract: tile parser for marketplace listings, else LLM --------
    from chubb_ci.config.sources import FetcherKind, PageType

    products: list[ExtractedProduct] = []
    is_listing = (source.fetcher is FetcherKind.BROWSER
                  and source.page_type is PageType.PRICING)

    # 官网 catalog spider: follow product-detail links from this listing/category page
    # and extract EVERY product (name + official image + specs). Deterministic, no LLM.
    if source.crawl_catalog and cleaned.fetch.html:
        products = _crawl_catalog_page(settings, source, url, cleaned.fetch.html)

    if not products and is_listing and cleaned.fetch.html:
        from chubb_ci.crawler.tiles import parse_tiles

        tiles = parse_tiles(cleaned.fetch.html, selectors=source.selectors,
                            brand=source.company, base_url=url)
        products = [_tile_to_product(t, url) for t in tiles]
        if products:
            logger.info("tile parser: {} products (with images) for {}",
                        len(products), source.name)

    # LLM fallback for 官网/news/detail (skip for catalog sources: their listing pages
    # are near-empty nav text → LLM would only hallucinate series names).
    if not products and not source.crawl_catalog:  # noqa: E501
        result = extract_products(
            llm, model=extract_model, source=source, url=url,
            page_text=cleaned.main_text, domain_context=domain_context,
            temperature=settings.llm_temperature,
        )
        summary.tokens_in += result.tokens_in
        summary.tokens_out += result.tokens_out
        if not result.ok:
            summary.sources_failed += 1
            repo.add_snapshot(Snapshot(
                run_id=run_id, source_name=source.name, company=source.company, url=url,
                page_type=source.page_type.value, channel=source.channel,
                content_hash=cleaned.content_hash, status=SnapshotStatus.ERROR.value,
                error=result.error, raw_path=raw_path,
            ))
            return
        products = list(result.products)

    # --- detail-page enrichment (fill specs from a bounded # of detail pages) ---
    if is_listing and source.enrich_details:
        _enrich_details(settings, source, products, summary)

    snapshot = repo.add_snapshot(Snapshot(
        run_id=run_id, source_name=source.name, company=source.company, url=url,
        page_type=source.page_type.value, channel=source.channel,
        content_hash=cleaned.content_hash, status=SnapshotStatus.OK.value,
        raw_path=raw_path, num_products=len(products),
    ))
    summary.sources_ok += 1
    summary.products_extracted += len(products)

    records = [_to_record(p, snapshot_id=snapshot.id, run_id=run_id, source=source)
               for p in products]
    repo.add_products(records)

    # --- diff vs previous baseline -------------------------------------
    baseline = repo.last_ok_snapshot(source.name, before_id=snapshot.id)
    if baseline is None:
        summary.baselines += 1
        logger.info("baseline captured ({} products, no prior data to diff): {} {}",
                    len(products), source.name, url)
        return

    previous = [record_to_extracted(r) for r in repo.products_for_snapshot(baseline.id)]
    current = [record_to_extracted(r) for r in records]
    events = diff_products(previous, current, price_change_min_pct=settings.price_change_min_pct)
    if events:
        repo.add_events(_events_to_rows(events, run_id=run_id, source=source))
        summary.events_detected += len(events)
        logger.info("{} change(s) for {}", len(events), source.name)


# =========================================================================
# Reporting
# =========================================================================
def generate_daily(
    settings: Settings,
    *,
    run_id: int | None = None,
    llm: LLMClient | None = None,
    use_llm: bool = True,
) -> ReportDraft:
    """Build + persist + export the daily digest for the given run's events.

    ``use_llm=False`` forces the deterministic (no-LLM) digest without constructing a
    client — used by the offline demo and tests.
    """
    settings = settings or get_settings()
    if use_llm:
        llm = llm if llm is not None else build_llm(settings)
        model = resolve_model(settings, "daily")
    else:
        llm, model = None, ""

    from chubb_ci.summary.facts import format_insight_facts

    with session_scope(settings) as session:
        repo = Repository(session)
        if run_id is None:
            events, products = [], []
        else:
            events = repo.events_for_run(run_id)
            products = repo.products_for_run(run_id)
        insight_facts = format_insight_facts(repo.all_insights())

        draft = build_daily_report(events, llm=llm, model=model, insight_facts=insight_facts)
        _persist_and_export(settings, repo, draft, ReportType.DAILY, run_id, events, products)
    return draft


def generate_weekly(
    settings: Settings,
    *,
    run_id: int | None = None,
    days: int = 7,
    llm: LLMClient | None = None,
    use_llm: bool = True,
) -> ReportDraft:
    """Build + persist + export the weekly report over the trailing ``days``."""
    settings = settings or get_settings()
    if use_llm:
        llm = llm if llm is not None else build_llm(settings)
        model = resolve_model(settings, "weekly")
    else:
        llm, model = None, ""

    from chubb_ci.summary.facts import format_insight_facts

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    with session_scope(settings) as session:
        repo = Repository(session)
        events = repo.events_between(start, end)
        products = repo.products_for_run(run_id) if run_id else []
        insight_facts = format_insight_facts(repo.all_insights())
        draft = build_weekly_report(
            events, llm=llm, model=model,
            period_start=start.date(), period_end=end.date(),
            insight_facts=insight_facts,
        )
        _persist_and_export(settings, repo, draft, ReportType.WEEKLY, run_id, events, products)
    return draft


def _persist_and_export(settings, repo, draft, report_type, run_id, events, products) -> None:
    repo.add_report(Report(
        run_id=run_id, report_type=report_type.value, title=draft.title,
        content_md=draft.content_md, model_used=draft.model_used, num_events=draft.num_events,
        period_end=datetime.now(timezone.utc),
    ))
    sink = ExcelSink(settings.reports_path)
    sink.write_report(draft, report_type=report_type.value)
    sink.export_tables(events=events, products=products, run_id=run_id)


# =========================================================================
# Convenience entrypoints (used by scheduler + CLI)
# =========================================================================
def run_daily(settings: Settings | None = None, *, llm: LLMClient | None = None) -> ReportDraft:
    settings = settings or get_settings()
    summary = run_crawl(settings, kind="daily", frequency_filter="daily", llm=llm)
    return generate_daily(settings, run_id=summary.run_id, llm=llm)


def run_weekly(settings: Settings | None = None, *, llm: LLMClient | None = None) -> ReportDraft:
    settings = settings or get_settings()
    summary = run_crawl(settings, kind="weekly", frequency_filter="weekly", llm=llm)
    return generate_weekly(settings, run_id=summary.run_id, llm=llm)
