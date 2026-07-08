"""Daily digest: short, facts-only summary of today's detected changes."""

from __future__ import annotations

from datetime import date

from loguru import logger

from chubb_ci.llm.base import LLMClient, LLMError
from chubb_ci.schemas.models import DiffEvent
from chubb_ci.summary.facts import ReportDraft, format_events_facts
from chubb_ci.summary.prompts import DAILY_SYSTEM, DAILY_USER


def build_daily_report(
    events: list[DiffEvent],
    *,
    llm: LLMClient | None = None,
    model: str = "",
    on_date: date | None = None,
    insight_facts: str = "",
) -> ReportDraft:
    """Produce a short daily digest.

    With no events or no LLM, returns a deterministic report (no API cost). The LLM
    only rephrases the pre-computed fact block(s), so it cannot hallucinate figures.
    ``insight_facts`` optionally appends the deterministic 对标/机会 analysis block.
    """
    on_date = on_date or date.today()
    facts = format_events_facts(events)
    if insight_facts:
        facts = f"{facts}\n\n{insight_facts}"
    title = f"集宝竞争情报 · 每日速报 {on_date.isoformat()}"

    if not events or llm is None:
        if events:
            body = facts
        else:
            # No changes today — still surface the standing 对标/机会 analysis.
            body = "今日未检测到竞争对手信息变化。"
            if insight_facts:
                body += f"\n\n{insight_facts}"
        return ReportDraft(
            title=title,
            content_md=f"# {title}\n\n{body}",
            model_used="deterministic",
            num_events=len(events),
        )

    try:
        resp = llm.complete(
            system=DAILY_SYSTEM,
            user=DAILY_USER.format(date=on_date.isoformat(), facts=facts),
            model=model,
            temperature=0.2,
        )
        content = f"# {title}\n\n{resp.content.strip()}\n\n---\n\n<details><summary>检测明细</summary>\n\n{facts}\n\n</details>"
        return ReportDraft(
            title=title,
            content_md=content,
            model_used=resp.model,
            num_events=len(events),
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
        )
    except LLMError as exc:
        logger.error("daily summary LLM failed ({}); using deterministic fallback", exc)
        return ReportDraft(
            title=title,
            content_md=f"# {title}\n\n> （LLM 生成失败，以下为检测明细）\n\n{facts}",
            model_used="deterministic-fallback",
            num_events=len(events),
        )
