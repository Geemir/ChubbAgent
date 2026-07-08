"""Seed the database with realistic demo data so the dashboard is populated.

Creates several Chinese safe competitors, a baseline + current snapshot per competitor
(so the Products page shows price diffs), a spread of historical change events (for the
trend/volatility charts), and deterministic daily + weekly reports.

Run:  chubb-ci seed-demo
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger
from sqlmodel import SQLModel

from chubb_ci.config.settings import Settings, get_settings
from chubb_ci.schemas.models import (
    CrawlRun,
    DiffEvent,
    EventType,
    ProductRecord,
    Report,
    ReportType,
    Snapshot,
    SnapshotStatus,
)
from chubb_ci.storage.db import get_engine, init_db, session_scope
from chubb_ci.storage.repositories import Repository
from chubb_ci.summary.daily import build_daily_report
from chubb_ci.summary.weekly import build_weekly_report

# (company, source_name, url, channel, [products])
# product = (name, category, baseline_price, current_price, gb_grade, lock_type,
#            fire_rating, capacity_l, weight_kg, lead_days, promotion, availability, state)
#   state: "both" | "new" (only current) | "gone" (only baseline / discontinued)
_COMPETITORS = [
    ("艾谱 AIPU", "aipu", "https://www.aipu.cn", "官网", [
        ("艾谱 FDX-A/D-30 指纹保险箱", "保险箱", 1299, 1299, "A", "指纹", None, 30, 40, 3, None, "有货", "both"),
        ("艾谱 大将军系列 智能保险柜", "保险柜", 3199, 2999, "B", "指纹+密码", None, 120, 150, 7, None, "有货", "both"),
        ("艾谱 A1 家用小型保险箱", "保险箱", 699, 699, "A", "电子", None, 20, 22, 3, "满699减100", "有货", "both"),
        ("艾谱 欧盾系列 全钢防盗柜", "保险柜", 4599, 4599, "C", "机械", None, 150, 210, 10, None, "有货", "both"),
        ("艾谱 FDG 防火防水保险箱", "防火柜", 1899, 1899, "A", "电子", "EN15659/30min", 25, 45, 5, None, "有货", "both"),
    ]),
    ("虎牌 Tiger", "tiger", "https://www.tiger-safe.com", "官网", [
        ("虎牌 3C认证保险柜 45cm", "保险柜", 999, 1099, "A", "电子", None, 45, 50, 3, None, "有货", "both"),
        ("虎牌 指纹小型保险箱", "保险箱", 899, 899, "A", "指纹", None, 20, 21, 3, None, "有货", "both"),
        ("虎牌 大型全能保险柜 1米", "保险柜", 3299, 3299, "B", "指纹", None, 100, 120, 7, None, "有货", "both"),
        ("虎牌 办公防盗保险柜", "保险柜", 1599, 1599, "A", "电子", None, 60, 70, 5, None, "有货", "both"),
    ]),
    ("永发 Yongfa", "yongfa", "https://www.yongfa-safe.com", "官网", [
        ("永发 D-73II 保管箱", "保管箱", 2399, 2399, "B", "双保险", None, 73, 95, 7, None, "缺货", "both"),
        ("永发 银行级金库门", "金库门", 25999, 25999, "C", "机械", None, None, 800, 30, None, "有货", "both"),
        ("永发 家用指纹保险柜", "保险柜", 1799, 1799, "A", "指纹", "国标30min", 55, 62, 7, "618直降300", "有货", "both"),
        ("永发 商用大型保险柜", "保险柜", 5299, 5299, "B", "指纹+密码", None, 180, 260, 15, None, "有货", "both"),
        ("永发 防磁信息保险柜", "防火柜", 3999, 3999, "A", "电子", "EN1047-1 60min", 40, 88, 10, None, "有货", "both"),
    ]),
    ("迪堡 Diebold", "diebold", "https://www.diebold.com.cn", "官网", [
        ("迪堡 金融机具保险柜", "保险柜", 8999, 8999, "C", "机械", "UL 60min", 200, 380, 20, None, "有货", "both"),
        ("迪堡 ATM存取款一体机", "ATM", 45999, 45999, None, "电子", None, None, None, 45, None, "有货", "both"),
        ("迪堡 商用金库门 VD-3", "金库门", 32999, 32999, "C", "机械", None, None, 1200, 60, None, "有货", "gone"),
    ]),
    ("得力 Deli", "deli", "https://www.nbdeli.com", "官网", [
        ("得力 4078 办公保险箱", "保险箱", 599, 599, "A", "电子", None, 25, 28, 2, None, "有货", "both"),
        ("得力 家用小型保险柜", "保险箱", 459, 459, "A", "电子", None, 17, 18, 2, None, "有货", "both"),
        ("得力 指纹办公保险柜", "保险柜", 899, 899, "A", "指纹", None, 50, 55, 3, None, "有货", "both"),
        ("得力 智能云保险柜 X1", "保险柜", 1099, 1099, "A", "指纹+APP", None, 55, 58, 5, None, "预售", "new"),
    ]),
    ("大一 Dayi", "dayi", "https://www.dayi-safe.com", "官网", [
        ("大一 3C保险柜 高80cm", "保险柜", 1399, 1399, "A", "电子", None, 80, 92, 5, None, "有货", "both"),
        ("大一 家用指纹保险箱", "保险箱", 899, 799, "A", "指纹", None, 30, 33, 5, None, "有货", "both"),
        ("大一 双门保险柜", "保险柜", 2199, 2199, "B", "指纹", None, 90, 110, 7, None, "有货", "both"),
    ]),
]


def _key(name: str) -> str:
    from chubb_ci.diff.matching import normalize_product_key

    return normalize_product_key(name)


def _fire_hours(text: str | None) -> float | None:
    from chubb_ci.normalize import fire_hours

    return fire_hours(text)


def _sec_score(gb: str | None) -> int | None:
    from chubb_ci.normalize import security_score

    return security_score(gb)


def _reset(settings: Settings) -> None:
    engine = get_engine(settings)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def seed(settings: Settings | None = None, *, reset: bool = True) -> dict:
    """Populate the DB with demo data. Returns a small summary dict."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    init_db(settings)
    if reset:
        _reset(settings)

    now = datetime.now(timezone.utc)
    rng = random.Random(42)

    with session_scope(settings) as session:
        repo = Repository(session)

        run_hist = CrawlRun(kind="seed-history", started_at=now - timedelta(minutes=5),
                            finished_at=now - timedelta(minutes=5), status="ok")
        run_today = CrawlRun(kind="seed", started_at=now, finished_at=now, status="ok")
        session.add(run_hist)
        session.add(run_today)
        session.commit()
        session.refresh(run_hist)
        session.refresh(run_today)

        total_products = 0
        today_events: list[DiffEvent] = []
        hist_events: list[DiffEvent] = []

        for company, sname, url, channel, products in _COMPETITORS:
            # baseline snapshot (3 days ago) + current snapshot (now)
            base_snap = repo.add_snapshot(Snapshot(
                run_id=run_hist.id, source_name=sname, company=company, url=url,
                page_type="product", channel=channel, status=SnapshotStatus.OK.value,
                crawl_time=now - timedelta(days=3),
            ))
            cur_snap = repo.add_snapshot(Snapshot(
                run_id=run_today.id, source_name=sname, company=company, url=url,
                page_type="product", channel=channel, status=SnapshotStatus.OK.value,
                crawl_time=now,
            ))

            base_recs, cur_recs = [], []
            for (name, cat, bp, cp, gb, lock, fire, cap, weight, lead,
                 promo, avail, state) in products:
                common = dict(source_name=sname, company=company, product_name=name,
                              product_key=_key(name), category=cat, currency="CNY",
                              gb_grade=gb, lock_type=lock, fire_rating=fire, capacity_l=cap,
                              weight_kg=weight, lead_time_days=lead,
                              fire_hours=_fire_hours(fire), security_score=_sec_score(gb))
                if state in ("both", "gone"):
                    base_recs.append(ProductRecord(
                        snapshot_id=base_snap.id, run_id=run_hist.id, price=bp,
                        availability="有货", crawl_time=now - timedelta(days=3), **common))
                if state in ("both", "new"):
                    cur_recs.append(ProductRecord(
                        snapshot_id=cur_snap.id, run_id=run_today.id, price=cp,
                        promotion=promo, availability=avail, crawl_time=now, **common))
                    total_products += 1

                # today events derived from baseline->current differences
                if state == "both" and bp != cp:
                    pct = round((cp - bp) / bp * 100, 1)
                    today_events.append(DiffEvent(
                        run_id=run_today.id, source_name=sname, company=company,
                        event_type=EventType.PRICE_CHANGE.value, product_key=_key(name),
                        product_name=name, field="price", old_value=str(bp),
                        new_value=str(cp), pct_change=pct, channel=channel,
                        source_url=url, detected_at=now))
                if state == "both" and promo:
                    today_events.append(DiffEvent(
                        run_id=run_today.id, source_name=sname, company=company,
                        event_type=EventType.PROMOTION_CHANGE.value, product_key=_key(name),
                        product_name=name, field="promotion", old_value=None,
                        new_value=promo, channel=channel, source_url=url, detected_at=now))
                if state == "both" and avail and avail != "有货":
                    today_events.append(DiffEvent(
                        run_id=run_today.id, source_name=sname, company=company,
                        event_type=EventType.STOCK_CHANGE.value, product_key=_key(name),
                        product_name=name, field="availability", old_value="有货",
                        new_value=avail, channel=channel, source_url=url, detected_at=now))
                if state == "new":
                    today_events.append(DiffEvent(
                        run_id=run_today.id, source_name=sname, company=company,
                        event_type=EventType.NEW_PRODUCT.value, product_key=_key(name),
                        product_name=name, field="price", new_value=str(cp),
                        channel=channel, source_url=url, detected_at=now))
                if state == "gone":
                    today_events.append(DiffEvent(
                        run_id=run_today.id, source_name=sname, company=company,
                        event_type=EventType.DISCONTINUED.value, product_key=_key(name),
                        product_name=name, old_value=str(bp), channel=channel,
                        source_url=url, detected_at=now))

            base_snap.num_products = len(base_recs)
            cur_snap.num_products = len(cur_recs)
            repo.add_products(base_recs + cur_recs)

            # historical events across the last 14 days (for trend/volatility)
            pickable = [p for p in products if p[12] == "both"]
            for _ in range(rng.randint(4, 8)):
                p = rng.choice(pickable)
                day = rng.randint(1, 13)
                old = p[2]
                pct = round(rng.uniform(-9, 6), 1)
                new = round(old * (1 + pct / 100))
                hist_events.append(DiffEvent(
                    run_id=run_hist.id, source_name=sname, company=company,
                    event_type=EventType.PRICE_CHANGE.value, product_key=_key(p[0]),
                    product_name=p[0], field="price", old_value=str(old),
                    new_value=str(new), pct_change=pct, channel=channel, source_url=url,
                    detected_at=now - timedelta(days=day, hours=rng.randint(0, 20))))

        repo.add_events(hist_events)
        repo.add_events(today_events)

        run_today.sources_ok = len(_COMPETITORS)
        run_today.products_extracted = total_products
        run_today.events_detected = len(today_events)
        session.add(run_today)
        session.commit()

        # brand profiles + real own catalog + counterpart pairs + market insights
        from chubb_ci.analytics.refresh import refresh_insights
        from chubb_ci.summary.facts import format_insight_facts
        from chubb_ci.tools.brand_sync import sync_brands, sync_counterparts
        from chubb_ci.tools.catalog_import import import_catalog

        root = Path(__file__).resolve().parents[1]
        n_brands = sync_brands(session, root / "config" / "brands.yaml")
        n_pairs = sync_counterparts(session, root / "config" / "counterparts.yaml")
        catalog = root / "ChubbProductsList.xlsx"
        n_own = import_catalog(session, catalog) if catalog.exists() else 0

        # Real competitor market data from the marketing deck (分析报告 channel).
        deck = root / "CompetitorAnalysisV7.pptx"
        n_deck = 0
        if deck.exists():
            from chubb_ci.tools.pptx_ingest import ingest_pptx

            n_deck = ingest_pptx(session, deck)["products"]

        insights = refresh_insights(repo, run_id=run_today.id)
        insight_facts = format_insight_facts(insights)

        # deterministic reports (offline; regenerate with LLM via `chubb-ci report`)
        daily = build_daily_report(today_events, llm=None, insight_facts=insight_facts)
        week_events = today_events + hist_events
        weekly = build_weekly_report(
            week_events, llm=None, insight_facts=insight_facts,
            period_start=(now - timedelta(days=7)).date(), period_end=now.date())
        repo.add_report(Report(run_id=run_today.id, report_type=ReportType.DAILY.value,
                               title=daily.title, content_md=daily.content_md,
                               model_used=daily.model_used, num_events=daily.num_events,
                               period_end=now))
        repo.add_report(Report(run_id=run_today.id, report_type=ReportType.WEEKLY.value,
                               title=weekly.title, content_md=weekly.content_md,
                               model_used=weekly.model_used, num_events=weekly.num_events,
                               period_end=now))

        summary = {
            "competitors": len(_COMPETITORS),
            "products": total_products,
            "today_events": len(today_events),
            "hist_events": len(hist_events),
            "brands": n_brands,
            "pairs": n_pairs,
            "own_products": n_own,
            "deck_products": n_deck,
            "insights": len(insights),
        }
    logger.info("seeded demo data: {}", summary)
    return summary
