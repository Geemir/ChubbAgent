"""Deterministic fact assembly from :class:`DiffEvent` rows.

The LLM only ever sees these pre-computed facts, so it cannot invent numbers — it can
only phrase what the diff engine already found. These functions also produce a
non-LLM fallback report.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from chubb_ci.schemas.models import DiffEvent, EventType, Insight

_EVENT_LABEL: dict[str, str] = {
    EventType.NEW_PRODUCT.value: "新品",
    EventType.DISCONTINUED.value: "下架/停产",
    EventType.PRICE_CHANGE.value: "价格变化",
    EventType.PROMOTION_CHANGE.value: "促销变化",
    EventType.SPEC_CHANGE.value: "规格变化",
    EventType.STOCK_CHANGE.value: "库存/上下架",
}


class ReportDraft(BaseModel):
    """A generated report ready to be persisted by the pipeline."""

    title: str
    content_md: str
    model_used: str = "deterministic"
    num_events: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class WeeklyStats(BaseModel):
    total_events: int = 0
    new_products: int = 0
    discontinued: int = 0
    price_changes: int = 0
    promotion_changes: int = 0
    spec_changes: int = 0
    stock_changes: int = 0
    avg_price_pct: float | None = None
    max_price_drop_pct: float | None = None
    max_price_rise_pct: float | None = None
    companies: list[str] = []


def _fmt_event(e: DiffEvent) -> str:
    label = _EVENT_LABEL.get(e.event_type, e.event_type)
    if e.event_type == EventType.PRICE_CHANGE.value:
        pct = f"（{e.pct_change:+.1f}%）" if e.pct_change is not None else ""
        return f"[{label}] {e.product_name}：{e.old_value} → {e.new_value}{pct}"
    if e.event_type == EventType.NEW_PRODUCT.value:
        price = f"，价格 {e.new_value}" if e.new_value else ""
        return f"[{label}] {e.product_name}{price}"
    if e.event_type == EventType.DISCONTINUED.value:
        return f"[{label}] {e.product_name}"
    if e.event_type in (EventType.PROMOTION_CHANGE.value, EventType.STOCK_CHANGE.value):
        return f"[{label}] {e.product_name}：{e.old_value or '无'} → {e.new_value or '无'}"
    # spec_change
    return f"[{label}] {e.product_name} · {e.field}：{e.old_value or '无'} → {e.new_value or '无'}"


def format_events_facts(events: list[DiffEvent]) -> str:
    """Deterministic markdown fact block, grouped by competitor."""
    if not events:
        return "本期未检测到竞争对手信息变化。"
    by_company: dict[str, list[DiffEvent]] = defaultdict(list)
    for e in events:
        by_company[e.company or "未知"].append(e)

    lines: list[str] = []
    for company in sorted(by_company):
        lines.append(f"### {company}")
        for e in by_company[company]:
            lines.append(f"- {_fmt_event(e)}")
        lines.append("")
    return "\n".join(lines).strip()


_INSIGHT_LABEL = {
    "pricing_anomaly": "定价异常",
    "market_gap": "市场空档",
    "logistics_advantage": "物流优势",
}


def format_insight_facts(insights: list[Insight]) -> str:
    """Deterministic markdown block of current market insights (对标/机会分析).

    Fed to the LLM alongside change events so reports can reference benchmarking
    findings — still strictly facts-only.
    """
    if not insights:
        return ""
    lines = ["### 对标与机会分析（系统计算）"]
    for i in insights:
        label = _INSIGHT_LABEL.get(i.insight_type, i.insight_type)
        lines.append(f"- [{label}] {i.title}：{i.detail}")
    return "\n".join(lines)


def aggregate_week(events: list[DiffEvent]) -> WeeklyStats:
    """Compute deterministic weekly statistics for the report intro."""
    stats = WeeklyStats(total_events=len(events))
    price_pcts: list[float] = []
    companies: set[str] = set()
    for e in events:
        companies.add(e.company or "未知")
        if e.event_type == EventType.NEW_PRODUCT.value:
            stats.new_products += 1
        elif e.event_type == EventType.DISCONTINUED.value:
            stats.discontinued += 1
        elif e.event_type == EventType.PRICE_CHANGE.value:
            stats.price_changes += 1
            if e.pct_change is not None:
                price_pcts.append(e.pct_change)
        elif e.event_type == EventType.PROMOTION_CHANGE.value:
            stats.promotion_changes += 1
        elif e.event_type == EventType.SPEC_CHANGE.value:
            stats.spec_changes += 1
        elif e.event_type == EventType.STOCK_CHANGE.value:
            stats.stock_changes += 1

    if price_pcts:
        stats.avg_price_pct = round(sum(price_pcts) / len(price_pcts), 2)
        stats.max_price_drop_pct = round(min(price_pcts), 2)
        stats.max_price_rise_pct = round(max(price_pcts), 2)
    stats.companies = sorted(companies)
    return stats


def stats_block(stats: WeeklyStats) -> str:
    """Deterministic markdown table of weekly stats."""
    rows = [
        ("检测到的变化总数", stats.total_events),
        ("新品", stats.new_products),
        ("下架/停产", stats.discontinued),
        ("价格变化", stats.price_changes),
        ("促销变化", stats.promotion_changes),
        ("规格变化", stats.spec_changes),
        ("库存/上下架", stats.stock_changes),
    ]
    lines = ["| 指标 | 数量 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    if stats.avg_price_pct is not None:
        lines.append(f"| 平均价格变动 | {stats.avg_price_pct:+.1f}% |")
        lines.append(f"| 最大降价 | {stats.max_price_drop_pct:+.1f}% |")
        lines.append(f"| 最大涨价 | {stats.max_price_rise_pct:+.1f}% |")
    return "\n".join(lines)
