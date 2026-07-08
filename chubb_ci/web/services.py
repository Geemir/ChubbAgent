"""DashboardService — compute view models for each page from the database.

Pure-ish read layer: takes a :class:`Repository` and returns plain dicts the Jinja
templates consume. Kept free of FastAPI so it is unit-testable on its own.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from chubb_ci.analytics.refresh import build_comparisons
from chubb_ci.config.settings import Settings
from chubb_ci.config.sources import load_sources
from chubb_ci.normalize import price_per_kg, price_per_l
from chubb_ci.schemas.models import DiffEvent, EventType, Insight, ProductRecord
from chubb_ci.storage.repositories import Repository

_INSIGHT_LABEL = {
    "pricing_anomaly": "定价异常",
    "market_gap": "市场空档",
    "logistics_advantage": "物流优势",
}

_SEVERITY_ORDER = ["Low", "Med", "High", "Crit"]

_EVENT_LABEL = {
    EventType.NEW_PRODUCT.value: "新品",
    EventType.DISCONTINUED.value: "下架/停产",
    EventType.PRICE_CHANGE.value: "价格变化",
    EventType.PROMOTION_CHANGE.value: "促销变化",
    EventType.SPEC_CHANGE.value: "规格变化",
    EventType.STOCK_CHANGE.value: "库存/上下架",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize possibly-naive DB timestamps to UTC-aware for safe comparison."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_severity(e: DiffEvent) -> str:
    """Map a change event to a severity bucket (Low/Med/High/Crit)."""
    t = e.event_type
    if t == EventType.PRICE_CHANGE.value and e.pct_change is not None:
        mag = abs(e.pct_change)
        if mag >= 15:
            return "Crit"
        if mag >= 8:
            return "High"
        if mag >= 3:
            return "Med"
        return "Low"
    if t == EventType.DISCONTINUED.value:
        return "High"
    if t in (EventType.NEW_PRODUCT.value, EventType.PROMOTION_CHANGE.value,
             EventType.STOCK_CHANGE.value):
        return "Med"
    return "Low"


def _time_ago(dt: datetime | None) -> str:
    dt = _aware(dt)
    if dt is None:
        return "—"
    delta = _now() - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    days = int(secs // 86400)
    return "昨天" if days == 1 else f"{days} 天前"


def _feed_summary(e: DiffEvent) -> str:
    label = _EVENT_LABEL.get(e.event_type, e.event_type)
    if e.event_type == EventType.PRICE_CHANGE.value:
        pct = f"（{e.pct_change:+.1f}%）" if e.pct_change is not None else ""
        return f"{label}：{e.product_name} 由 {e.old_value} 调整为 {e.new_value}{pct}。"
    if e.event_type == EventType.NEW_PRODUCT.value:
        price = f"，定价 {e.new_value}" if e.new_value else ""
        return f"{label}：检测到 {e.company} 上架 {e.product_name}{price}。"
    if e.event_type == EventType.DISCONTINUED.value:
        return f"{label}：{e.company} 的 {e.product_name} 已下架。"
    if e.event_type == EventType.PROMOTION_CHANGE.value:
        return f"{label}：{e.product_name} 促销由「{e.old_value or '无'}」变为「{e.new_value or '无'}」。"
    if e.event_type == EventType.STOCK_CHANGE.value:
        return f"{label}：{e.product_name} 库存状态 {e.old_value or '无'} → {e.new_value or '无'}。"
    return f"{label}：{e.product_name} · {e.field} {e.old_value or '无'} → {e.new_value or '无'}。"


class DashboardService:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    # ------------------------------------------------------------- sources
    def _sources(self):
        try:
            return load_sources(self.settings.sources_path)
        except Exception:
            return []

    # ------------------------------------------------------------- KPIs
    def kpis(self) -> dict:
        products = self.repo.all_products()
        latest = _latest_per_product(products)
        companies = {p.company for p in latest.values() if p.company}
        active_promos = sum(1 for p in latest.values() if _has_promo(p))
        today_start = _now() - timedelta(hours=24)
        changes_today = len(self.repo.events_between(today_start, _now()))
        return {
            "competitors_monitored": len(companies) or len({s.company for s in self._sources()}),
            "products_tracked": len(latest),
            "changes_today": changes_today,
            "active_promotions": active_promos,
            "newly_discovered": 0,  # Phase 2 (discovery agent)
        }

    # ------------------------------------------------- dashboard widgets
    def changes_trend(self, days: int = 14) -> dict:
        start = _now() - timedelta(days=days)
        events = self.repo.events_between(start, _now())
        buckets: dict[str, int] = {}
        for i in range(days):
            d = (start + timedelta(days=i + 1)).date().isoformat()
            buckets[d] = 0
        for e in events:
            d = _aware(e.detected_at).date().isoformat()
            if d in buckets:
                buckets[d] += 1
        return {"labels": list(buckets.keys()), "values": list(buckets.values())}

    def severity_index(self, days: int = 30) -> dict:
        start = _now() - timedelta(days=days)
        events = self.repo.events_between(start, _now())
        counts = {k: 0 for k in _SEVERITY_ORDER}
        for e in events:
            counts[event_severity(e)] += 1
        return {"labels": _SEVERITY_ORDER, "values": [counts[k] for k in _SEVERITY_ORDER]}

    def recent_feed(self, limit: int = 8) -> list[dict]:
        events = self.repo.recent_events(limit)
        return [
            {
                "company": e.company,
                "type_label": _EVENT_LABEL.get(e.event_type, e.event_type),
                "event_type": e.event_type,
                "severity": event_severity(e),
                "title": e.product_name,
                "summary": _feed_summary(e),
                "time_ago": _time_ago(e.detected_at),
            }
            for e in events
        ]

    # ------------------------------------------------- daily report page
    def daily(self) -> dict:
        report = self.repo.latest_report("daily")
        run = self.repo.latest_run()
        events = self.repo.events_for_run(run.id) if run else self.repo.recent_events(50)

        new_products = [e for e in events if e.event_type == EventType.NEW_PRODUCT.value]
        price_moves = [e for e in events if e.event_type == EventType.PRICE_CHANGE.value]
        promos = [e for e in events if e.event_type == EventType.PROMOTION_CHANGE.value]
        alerts = [e for e in events if event_severity(e) in ("High", "Crit")]

        srcs = self._sources()
        enabled = [s for s in srcs if s.enabled]
        return {
            "report": report,
            "report_md": report.content_md if report else "",
            "report_date": (_aware(report.created_at).date().isoformat() if report else
                            _now().date().isoformat()),
            "summary_line": (
                f"抓取完成：检测到 {len(price_moves)} 处价格变化、"
                f"{len(new_products)} 款新品，覆盖 {len({e.company for e in events})} 家竞争对手。"
            ),
            "active_crawlers": {"active": len(enabled), "total": len(srcs)},
            "new_products": [_product_card(e) for e in new_products[:6]],
            "price_moves": [_price_row(e) for e in price_moves],
            "promotions": [_promo_card(e) for e in promos[:6]],
            "alerts": [
                {"title": e.product_name, "summary": _feed_summary(e), "company": e.company}
                for e in alerts[:4]
            ],
        }

    # ------------------------------------------------- competitors page
    def competitors(self) -> list[dict]:
        products = self.repo.all_products()
        latest = _latest_per_product(products)
        by_company_products: dict[str, set[str]] = defaultdict(set)
        for p in latest.values():
            by_company_products[p.company].add(p.product_key)

        start30 = _now() - timedelta(days=30)
        events30 = self.repo.events_between(start30, _now())
        vol: dict[str, list[float]] = defaultdict(list)
        recent_change: dict[str, datetime] = {}
        for e in events30:
            if e.event_type == EventType.PRICE_CHANGE.value and e.pct_change is not None:
                vol[e.company].append(abs(e.pct_change))
            dt = _aware(e.detected_at)
            if e.company not in recent_change or dt > recent_change[e.company]:
                recent_change[e.company] = dt

        # Group sources by company for URL + region + last crawl.
        srcs = self._sources()
        companies: dict[str, dict] = {}
        for s in srcs:
            c = companies.setdefault(s.company, {"name": s.company, "urls": [], "channels": set()})
            c["urls"].append(s.urls[0] if s.urls else "")
            c["channels"].add(s.channel)

        # Also include companies present in data but not in sources.
        for company in by_company_products:
            companies.setdefault(company, {"name": company, "urls": [], "channels": set()})

        # And every profiled brand (config/brands.yaml), even before any data exists.
        focus_map: dict[str, bool] = {}
        profiled: set[str] = set()
        for b in self.repo.all_brands():
            if b.is_own:
                continue
            companies.setdefault(b.name, {"name": b.name, "urls": [], "channels": set()})
            focus_map[b.name] = b.is_focus
            profiled.add(b.name)

        out = []
        for name, meta in companies.items():
            last_snap = None
            for s in srcs:
                if s.company == name:
                    snap = self.repo.last_snapshot(s.name)
                    if snap and (last_snap is None or _aware(snap.crawl_time) > _aware(last_snap.crawl_time)):
                        last_snap = snap
            v = vol.get(name, [])
            changed_recently = (
                name in recent_change and (_now() - recent_change[name]) < timedelta(hours=24)
            )
            out.append({
                "name": name,
                "url": meta["urls"][0] if meta["urls"] else "",
                "channels": "、".join(sorted(c for c in meta["channels"] if c)),
                "monitored_products": len(by_company_products.get(name, set())),
                "last_crawl": _time_ago(last_snap.crawl_time) if last_snap else "未抓取",
                "volatility": round(sum(v) / len(v), 1) if v else 0.0,
                "status": "change" if changed_recently else "active",
                "is_focus": focus_map.get(name, False),
                "has_profile": name in profiled,
            })
        # 重点关注 first, then by data richness.
        out.sort(key=lambda c: (not c["is_focus"], -c["monitored_products"], c["name"]))
        return out

    def toggle_focus(self, name: str) -> bool:
        """Flip the 重点关注 flag for a brand (stub row created if needed)."""
        from chubb_ci.schemas.models import Brand

        brand = self.repo.brand_by_name(name)
        if brand is None:
            brand = Brand(name=name, is_focus=True)
            self.repo.session.add(brand)
        else:
            brand.is_focus = not brand.is_focus
            self.repo.session.add(brand)
        self.repo.session.commit()
        return brand.is_focus

    # ------------------------------------------------- products page
    def products(self) -> dict:
        products = self.repo.all_products()
        by_key: dict[tuple[str, str], list[ProductRecord]] = defaultdict(list)
        for p in products:
            by_key[(p.company, p.product_key)].append(p)

        rows = []
        categories: set[str] = set()
        companies: set[str] = set()
        for (company, _key), recs in by_key.items():
            recs.sort(key=lambda r: _aware(r.crawl_time))
            cur = recs[-1]
            prev = _prev_priced(recs)
            diff_pct = None
            if prev and prev.price not in (None, 0) and cur.price is not None:
                diff_pct = round((cur.price - prev.price) / prev.price * 100, 1)
            if cur.category:
                categories.add(cur.category)
            if company:
                companies.add(company)
            rows.append({
                "product_name": cur.product_name,
                "company": company,
                "category": cur.category or "—",
                "price": cur.price,
                "prev_price": prev.price if prev else None,
                "diff_pct": diff_pct,
                "promotion": cur.promotion,
                "gb_grade": cur.gb_grade,
                "capacity_l": cur.capacity_l,
                "weight_kg": cur.weight_kg,
                "fire_hours": cur.fire_hours,
                "security_score": cur.security_score,
                "price_per_l": price_per_l(cur.price, cur.capacity_l),
                "price_per_kg": price_per_kg(cur.price, cur.weight_kg),
                "lead_time_days": cur.lead_time_days,
                "status_label": cur.status_label,
                "last_updated": _time_ago(cur.crawl_time),
            })
        rows.sort(key=lambda r: (r["company"], r["product_name"]))
        return {
            "rows": rows,
            "categories": sorted(categories),
            "companies": sorted(companies),
        }

    # ------------------------------------------------- insights (dashboard)
    def insight_summary(self) -> dict:
        insights = self.repo.all_insights()
        counts = {"pricing_anomaly": 0, "market_gap": 0, "logistics_advantage": 0}
        for i in insights:
            if i.insight_type in counts:
                counts[i.insight_type] += 1
        return {
            "counts": counts,
            "total": len(insights),
            "items": [self._insight_view(i) for i in insights],
        }

    @staticmethod
    def _insight_view(i: Insight) -> dict:
        return {
            "type": i.insight_type,
            "type_label": _INSIGHT_LABEL.get(i.insight_type, i.insight_type),
            "severity": i.severity,
            "title": i.title,
            "detail": i.detail,
            "company": i.company,
        }

    # ------------------------------------------------- benchmark page (对标)
    def benchmark(self) -> dict:
        comparisons, _bands, own, _ = build_comparisons(self.repo)
        rows = []
        for c in comparisons:
            d = c.model_dump()
            d["lead_advantage"] = c.lead_delta is not None and c.lead_delta < 0
            d["vfm_good"] = c.vfm_index is not None and c.vfm_index > 1
            rows.append(d)
        rows.sort(key=lambda r: (r["comp_company"], r["own_name"]))
        return {
            "rows": rows,
            "own_count": len(own),
            "pair_count": len(rows),
        }

    # ------------------------------------------------- market map page
    def market_map(self) -> dict:
        _comparisons, bands, own, comp_list = build_comparisons(self.repo)

        # Scatter: one series per competitor brand + one for 集宝 (highlighted).
        scatter: dict[str, list[dict]] = defaultdict(list)
        for p in comp_list:
            if p.price and p.capacity_l:
                scatter[p.company].append(
                    {"x": p.capacity_l, "y": p.price, "name": p.product_name})
        own_points = [
            {"x": p.capacity_l, "y": p.price, "name": p.product_name}
            for p in own if p.price and p.capacity_l
        ]

        # Quadrant: per brand — avg price (X) vs avg security score (Y), sized by count.
        quad = []
        by_company: dict[str, list[ProductRecord]] = defaultdict(list)
        for p in comp_list:
            by_company[p.company].append(p)
        for company, items in by_company.items():
            prices = [p.price for p in items if p.price]
            scores = [p.security_score for p in items if p.security_score]
            if prices:
                quad.append({
                    "brand": company, "own": False,
                    "avg_price": round(sum(prices) / len(prices), 0),
                    "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
                    "count": len(items),
                })
        own_prices = [p.price for p in own if p.price]
        own_scores = [p.security_score for p in own if p.security_score]
        if own_prices:
            quad.append({
                "brand": "集宝 ChubbSafes", "own": True,
                "avg_price": round(sum(own_prices) / len(own_prices), 0),
                "avg_score": round(sum(own_scores) / len(own_scores), 1) if own_scores else 0,
                "count": len(own),
            })

        return {
            "scatter": dict(scatter),
            "own_points": own_points,
            "bands": [b.model_dump() for b in bands],
            "quad": quad,
            "own_count": len(own),
        }

    # ------------------------------------------------- brand profile page
    def brand_profile(self, name: str) -> dict | None:
        brand = self.repo.brand_by_name(name)
        # Fall back: profile pages also work for crawled companies without a profile.
        products = [
            p for p in _latest_per_product(self.repo.all_products()).values()
            if p.company == name
        ]
        if brand is None and not products:
            return None
        products.sort(key=lambda p: (p.series or "", p.product_name))
        prod_rows = [{
            "product_name": p.product_name, "series": p.series, "category": p.category,
            "price": p.price, "capacity_l": p.capacity_l, "fire_hours": p.fire_hours,
            "security_score": p.security_score, "promotion": p.promotion,
            "availability": p.availability, "source_url": p.source_url,
        } for p in products]
        return {
            "brand": brand,
            "name": name,
            "products": prod_rows,
            "num_products": len(prod_rows),
        }

    # ------------------------------------------------- promotions page
    def promotions(self) -> dict:
        latest = _latest_per_product(self.repo.all_products())
        items = []
        for p in latest.values():
            if _has_promo(p):
                items.append({
                    "company": p.company,
                    "product_name": p.product_name,
                    "promotion": p.promotion,
                    "promotion_end_date": p.promotion_end_date,
                    "category": p.category,
                    "price": p.price,
                    "source_url": p.source_url,
                })
        items.sort(key=lambda x: (x["company"], x["product_name"]))
        return {"items": items, "companies": sorted({i["company"] for i in items})}

    # ------------------------------------------------- price changes page
    def price_changes(self, days: int = 90) -> dict:
        start = _now() - timedelta(days=days)
        events = [e for e in self.repo.events_between(start, _now())
                  if e.event_type == EventType.PRICE_CHANGE.value]
        events.sort(key=lambda e: _aware(e.detected_at), reverse=True)

        rows, pcts, companies = [], [], set()
        ups = downs = 0
        for e in events:
            if e.pct_change is not None:
                pcts.append(e.pct_change)
                if e.pct_change > 0:
                    ups += 1
                elif e.pct_change < 0:
                    downs += 1
            companies.add(e.company)
            rows.append({
                "company": e.company, "product_name": e.product_name,
                "old_value": e.old_value, "new_value": e.new_value,
                "pct_change": e.pct_change, "channel": e.channel,
                "date": _aware(e.detected_at).date().isoformat(),
                "severity": event_severity(e),
            })
        stats = {"total": len(rows), "ups": ups, "downs": downs,
                 "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else 0.0}
        return {"rows": rows, "stats": stats, "companies": sorted(companies)}

    # ------------------------------------------------- market trends page
    def market_trends(self, days: int = 30) -> dict:
        start = _now() - timedelta(days=days)
        events = self.repo.events_between(start, _now())

        up: dict[str, int] = {}
        down: dict[str, int] = {}
        for i in range(days):
            d = (start + timedelta(days=i + 1)).date().isoformat()
            up[d] = 0
            down[d] = 0
        for e in events:
            if e.event_type == EventType.PRICE_CHANGE.value and e.pct_change is not None:
                d = _aware(e.detected_at).date().isoformat()
                if d in up:
                    (up if e.pct_change >= 0 else down)[d] += 1

        cat: dict[str, int] = defaultdict(int)
        for p in _latest_per_product(self.repo.all_products()).values():
            cat[p.category or "其他"] += 1

        comp: dict[str, int] = defaultdict(int)
        etype: dict[str, int] = defaultdict(int)
        for e in events:
            comp[e.company or "未知"] += 1
            etype[_EVENT_LABEL.get(e.event_type, e.event_type)] += 1

        comp_sorted = sorted(comp.items(), key=lambda kv: kv[1], reverse=True)
        cat_sorted = sorted(cat.items(), key=lambda kv: kv[1], reverse=True)
        return {
            "price_direction": {"labels": list(up.keys()),
                                "up": list(up.values()), "down": list(down.values())},
            "categories": {"labels": [k for k, _ in cat_sorted],
                           "values": [v for _, v in cat_sorted]},
            "competitor_activity": {"labels": [k for k, _ in comp_sorted],
                                    "values": [v for _, v in comp_sorted]},
            "event_types": {"labels": list(etype.keys()), "values": list(etype.values())},
            "total_events": len(events),
        }


# =========================================================================
# helpers
# =========================================================================
def _has_promo(p: ProductRecord) -> bool:
    return bool(p.promotion and p.promotion.strip())


def _latest_per_product(products: list[ProductRecord]) -> dict[tuple[str, str], ProductRecord]:
    latest: dict[tuple[str, str], ProductRecord] = {}
    for p in products:
        key = (p.company, p.product_key)
        cur = latest.get(key)
        if cur is None or _aware(p.crawl_time) >= _aware(cur.crawl_time):
            latest[key] = p
    return latest


def _prev_priced(recs: list[ProductRecord]) -> ProductRecord | None:
    """Most recent earlier record whose price differs from the current one."""
    if len(recs) < 2:
        return None
    cur = recs[-1]
    for r in reversed(recs[:-1]):
        if r.price != cur.price:
            return r
    return recs[-2]


def _product_card(e: DiffEvent) -> dict:
    return {"name": e.product_name, "company": e.company, "price": e.new_value,
            "url": e.source_url}


def _price_row(e: DiffEvent) -> dict:
    return {
        "company": e.company, "product_name": e.product_name,
        "old_value": e.old_value, "new_value": e.new_value,
        "pct_change": e.pct_change,
    }


def _promo_card(e: DiffEvent) -> dict:
    return {"product_name": e.product_name, "company": e.company,
            "promotion": e.new_value or e.old_value, "url": e.source_url}
