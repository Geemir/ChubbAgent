"""End-to-end pipeline: fetch → extract → diff → store → report → export.

This module is the single orchestration point shared by the CLI and the scheduler.
Each source is processed independently; one failing source never aborts the run.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from loguru import logger
from pydantic import BaseModel

from chubb_ci.config.settings import Settings, get_settings
from chubb_ci.config.sources import Source, enabled_sources, load_sources
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
    sources_skipped: int = 0
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
    from chubb_ci.normalize import fire_hours, security_score, volume_l

    # Deterministic standardization at ingest (never computed by the LLM).
    capacity = p.capacity_l or volume_l(p.width_mm, p.depth_mm, p.height_mm)
    return ProductRecord(
        snapshot_id=snapshot_id,
        run_id=run_id,
        source_name=source.name,
        company=source.company,
        product_name=p.product_name,
        product_key=p.product_key(),
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
        source_url=p.source_url,
        fire_hours=fire_hours(p.fire_rating),
        security_score=security_score(p.gb_grade, p.euro_grade),
    )


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
) -> CrawlSummary:
    """Fetch + extract + diff all due sources; persist snapshots, products, events."""
    settings = settings or get_settings()
    init_db(settings)
    llm = llm or build_llm(settings)
    extract_model = resolve_model(settings, "extract")
    domain_context = settings.load_domain_context()
    override_urls = override_urls or {}

    sources = enabled_sources(load_sources(settings.sources_path), frequency_filter)
    logger.info("crawl kind={} sources={}", kind, [s.name for s in sources])

    with session_scope(settings) as session:
        repo = Repository(session)
        run = repo.create_run(kind)
        summary = CrawlSummary(run_id=run.id, kind=kind)

        for source in sources:
            for raw_url in source.urls:
                url = override_urls.get(raw_url, raw_url)
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
        run.sources_skipped = summary.sources_skipped
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
        "crawl done: ok={} failed={} skipped={} products={} events={} cost≈¥{}",
        summary.sources_ok, summary.sources_failed, summary.sources_skipped,
        summary.products_extracted, summary.events_detected, summary.est_cost_cny,
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
        status = SnapshotStatus.BLOCKED if cleaned.fetch.blocked else SnapshotStatus.ERROR
        summary.sources_failed += 1
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

    # --- extract --------------------------------------------------------
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

    snapshot = repo.add_snapshot(Snapshot(
        run_id=run_id, source_name=source.name, company=source.company, url=url,
        page_type=source.page_type.value, channel=source.channel,
        content_hash=cleaned.content_hash, status=SnapshotStatus.OK.value,
        raw_path=raw_path, num_products=len(result.products),
    ))
    summary.sources_ok += 1
    summary.products_extracted += len(result.products)

    records = [_to_record(p, snapshot_id=snapshot.id, run_id=run_id, source=source)
               for p in result.products]
    repo.add_products(records)

    # --- diff vs previous baseline -------------------------------------
    baseline = repo.last_ok_snapshot(source.name, before_id=snapshot.id)
    if baseline is None:
        logger.info("baseline snapshot recorded (no diff): {} {}", source.name, url)
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
