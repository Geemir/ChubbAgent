"""Agent service: start workflows (blocking or background) and apply human reviews."""

from __future__ import annotations

import threading

from loguru import logger
from sqlmodel import Session, select

from chubb_ci.agent.runtime import AgentContext, create_run, finish_run
from chubb_ci.agent.search import build_search
from chubb_ci.config.settings import Settings
from chubb_ci.llm.base import LLMClient
from chubb_ci.llm.factory import build_llm
from chubb_ci.schemas.models import AgentRun, Brand, PendingFact, ProductRecord
from chubb_ci.storage.db import session_scope

WORKFLOWS = ("ingest", "research", "enrich", "sentiment")

_BRAND_FIELDS = {"positioning", "competition_tier", "target_audience",
                 "market_scale", "supply_chain", "warranty"}


def _execute(settings: Settings, run_id: int, workflow: str, params: dict,
             llm: LLMClient | None = None, search=None) -> None:
    """Run one workflow inside its own session (thread-safe entrypoint)."""
    with session_scope(settings) as session:
        run = session.get(AgentRun, run_id)
        ctx = AgentContext(session, settings, run)
        llm = llm or build_llm(settings)
        search = search if search is not None else build_search(settings)
        try:
            if workflow == "ingest":
                from chubb_ci.agent.ingest_flow import run_ingest

                run_ingest(ctx, llm, params["path"])
            elif workflow == "research":
                from chubb_ci.agent.research_flow import run_research

                run_research(ctx, llm, search,
                             brand=params["brand"], url=params.get("url"))
            elif workflow == "enrich":
                from chubb_ci.agent.enrich_flow import run_enrich

                run_enrich(ctx, llm, search, product_id=int(params["product_id"]))
            elif workflow == "sentiment":
                from chubb_ci.agent.sentiment_flow import run_sentiment

                run_sentiment(ctx, llm, search, goal=params.get("goal", ""))
            else:
                raise ValueError(f"unknown workflow: {workflow}")
        except Exception as exc:  # noqa: BLE001 - a failed run must never crash the app
            logger.exception("agent run #{} failed: {}", run_id, exc)
            try:
                finish_run(ctx, status="failed", error=str(exc))
            except Exception:  # noqa: BLE001
                pass


def start_workflow(
    settings: Settings, workflow: str, params: dict, *,
    background: bool = True, llm: LLMClient | None = None, search=None,
) -> int:
    """Create a run and execute it (in a daemon thread when ``background``)."""
    if workflow not in WORKFLOWS:
        raise ValueError(f"workflow must be one of {WORKFLOWS}")
    goal = (params.get("goal") or params.get("brand") or params.get("path")
            or (f"product:{params['product_id']}" if params.get("product_id") else workflow))
    with session_scope(settings) as session:
        run = create_run(session, workflow, str(goal))
        run_id = run.id
    if background:
        t = threading.Thread(target=_execute, args=(settings, run_id, workflow, params),
                             kwargs={"llm": llm, "search": search}, daemon=True,
                             name=f"agent-{run_id}")
        t.start()
    else:
        _execute(settings, run_id, workflow, params, llm=llm, search=search)
    return run_id


# =========================================================================
# Human review (采纳 / 驳回)
# =========================================================================
def review_fact(session: Session, fact_id: int, *, accept: bool, note: str = "") -> dict:
    """Apply or reject a pending fact. Accepted facts are written into the DB."""
    fact = session.get(PendingFact, fact_id)
    if fact is None:
        return {"error": "fact not found"}
    if fact.status in ("applied", "rejected"):
        return {"error": f"already {fact.status}"}

    if not accept:
        fact.status = "rejected"
        fact.review_note = note
        session.add(fact)
        session.commit()
        return {"status": "rejected"}

    applied_to = _apply_fact(session, fact)
    fact.status = "applied"
    fact.review_note = note or applied_to
    session.add(fact)
    session.commit()
    return {"status": "applied", "target": applied_to}


def _apply_fact(session: Session, fact: PendingFact) -> str:
    """Write an accepted fact into the right table. Returns a description."""
    from chubb_ci.agent.product_fields import (
        ENRICHABLE_PRODUCT_FIELDS,
        deserialize_fact_value,
        refresh_computed_fields,
    )
    from chubb_ci.diff.matching import normalize_product_key

    # Product fact: subject = "{brand}|{product_name}"
    if "|" in fact.subject:
        brand, product = fact.subject.split("|", 1)
        key = normalize_product_key(product)
        stmt = (select(ProductRecord)
                .where(ProductRecord.company == brand,
                       ProductRecord.product_key == key)
                .order_by(ProductRecord.crawl_time.desc()))  # type: ignore[union-attr]
        rec = session.exec(stmt).first()
        if rec is None:
            return f"未找到产品记录 {fact.subject}（仅标记采纳）"
        if fact.field not in ENRICHABLE_PRODUCT_FIELDS:
            return f"不支持的产品字段 {fact.field}（仅标记采纳）"
        try:
            value = deserialize_fact_value(fact.field, fact.value)
        except (TypeError, ValueError):
            return f"{fact.field} 无法解析（仅标记采纳）"
        setattr(rec, fact.field, value)
        refresh_computed_fields(rec)
        session.add(rec)
        session.commit()
        return f"已更新产品 {product} 的 {fact.field}"

    # Discovery candidate: create a focused brand stub for follow-up.
    if fact.field == "discovery":
        brand = session.exec(select(Brand).where(Brand.name == fact.subject)).first()
        if brand is None:
            brand = Brand(name=fact.subject, is_focus=True,
                          positioning=f"（智能体发现，待完善）{fact.claim}")
            session.add(brand)
            session.commit()
        return f"已创建品牌档案（重点关注）：{fact.subject}；可在 sources.yaml 添加其抓取源"

    # Brand-profile fact.
    if fact.field in _BRAND_FIELDS:
        brand = session.exec(select(Brand).where(Brand.name == fact.subject)).first()
        if brand is None:
            brand = Brand(name=fact.subject)
            session.add(brand)
        setattr(brand, fact.field, fact.value)
        session.add(brand)
        session.commit()
        return f"已更新品牌 {fact.subject} 的 {fact.field}"

    return "无匹配的落库目标（仅标记采纳）"
