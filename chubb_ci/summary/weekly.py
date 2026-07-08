"""Weekly report: aggregated trends + ChubbSafes-oriented recommendations."""

from __future__ import annotations

from datetime import date

from loguru import logger

from chubb_ci.llm.base import LLMClient, LLMError
from chubb_ci.schemas.models import DiffEvent
from chubb_ci.summary.facts import ReportDraft, aggregate_week, format_events_facts, stats_block
from chubb_ci.summary.prompts import WEEKLY_SYSTEM, WEEKLY_USER


def build_weekly_report(
    events: list[DiffEvent],
    *,
    llm: LLMClient | None = None,
    model: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    insight_facts: str = "",
) -> ReportDraft:
    """Produce a detailed weekly report from the week's detected changes.

    ``insight_facts`` appends the deterministic 对标/机会 block so the weekly report
    can include a benchmarking summary (对标摘要) grounded in computed numbers.
    """
    period_end = period_end or date.today()
    period_start = period_start or period_end
    stats = aggregate_week(events)
    facts = format_events_facts(events)
    if insight_facts:
        facts = f"{facts}\n\n{insight_facts}"
    table = stats_block(stats)
    title = f"集宝竞争情报 · 每周报告 {period_start.isoformat()} ~ {period_end.isoformat()}"

    if not events or llm is None:
        if events:
            body = facts
        else:
            body = "本周未检测到竞争对手信息变化。"
            if insight_facts:
                body += f"\n\n{insight_facts}"
        content = f"# {title}\n\n## 本周统计\n\n{table}\n\n## 变化明细\n\n{body}"
        return ReportDraft(
            title=title, content_md=content, model_used="deterministic", num_events=len(events)
        )

    try:
        resp = llm.complete(
            system=WEEKLY_SYSTEM,
            user=WEEKLY_USER.format(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                stats=table,
                facts=facts,
            ),
            model=model,
            temperature=0.3,
        )
        content = (
            f"# {title}\n\n{resp.content.strip()}\n\n---\n\n"
            f"## 附录：本周统计\n\n{table}\n\n"
            f"<details><summary>全部检测明细</summary>\n\n{facts}\n\n</details>"
        )
        return ReportDraft(
            title=title,
            content_md=content,
            model_used=resp.model,
            num_events=len(events),
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
        )
    except LLMError as exc:
        logger.error("weekly summary LLM failed ({}); using deterministic fallback", exc)
        content = f"# {title}\n\n> （LLM 生成失败，以下为统计与明细）\n\n## 本周统计\n\n{table}\n\n## 变化明细\n\n{facts}"
        return ReportDraft(
            title=title, content_md=content, model_used="deterministic-fallback",
            num_events=len(events),
        )
