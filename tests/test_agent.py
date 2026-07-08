"""Tests for the Phase C agent: verify node, workflows (FakeLLM), and human review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select

from chubb_ci.agent.service import review_fact, start_workflow
from chubb_ci.agent.state import SourcedFact
from chubb_ci.agent.verify import BASE_LLM, BASE_STRUCTURED, verify_facts
from chubb_ci.demo_seed import seed
from chubb_ci.llm.fake import FakeLLM
from chubb_ci.schemas.models import (
    AgentRun,
    AgentStepRecord,
    Brand,
    PendingFact,
    ProductRecord,
)
from chubb_ci.storage.db import session_scope

FIXTURES = Path(__file__).parent / "fixtures"
DECK = Path(__file__).resolve().parents[1] / "CompetitorAnalysisV7.pptx"


# =========================================================================
# Verify node
# =========================================================================
def F(**kw) -> SourcedFact:
    base = dict(claim="test", field="price", value="1999", subject="brand|prod",
                sources=["http://a.com"], confidence=BASE_LLM)
    base.update(kw)
    return SourcedFact(**base)


def test_verify_no_source_never_passes():
    vr = verify_facts([F(sources=[], confidence=0.99)])
    assert not vr.verified
    assert vr.pending[0].confidence == 0.0


def test_verify_corroboration_merges_and_boosts():
    facts = [F(sources=["http://a.com"]), F(sources=["http://b.com"])]
    vr = verify_facts(facts, threshold=0.8)
    merged = (vr.verified + vr.pending)[0]
    assert merged.corroborations == 2
    # 0.5 base + 0.2 corroboration + 0.15 price-sane = 0.85 → verified
    assert merged.status == "verified"


def test_verify_consistency_penalty():
    vr = verify_facts([F(value="不是数字", confidence=BASE_STRUCTURED)])
    assert vr.pending and vr.pending[0].confidence < BASE_STRUCTURED


def test_verify_single_source_llm_stays_pending():
    vr = verify_facts([F()], threshold=0.8)   # 0.5 + 0.15 = 0.65 < 0.8
    assert vr.pending and not vr.verified


def test_verify_price_band_check():
    bands = {"brand|prod": (1000.0, 3000.0)}
    ok = verify_facts([F(value="1999")], known_price_bands=bands)
    bad = verify_facts([F(value="99999999")], known_price_bands=bands)
    assert (ok.verified + ok.pending)[0].confidence > (bad.verified + bad.pending)[0].confidence


# =========================================================================
# Workflows (FakeLLM, foreground)
# =========================================================================
def _steps(settings, run_id):
    with session_scope(settings) as s:
        return [r.node for r in s.exec(
            select(AgentStepRecord).where(AgentStepRecord.run_id == run_id)).all()]


def test_scan_workflow(settings):
    seed(settings, reset=True)
    llm = FakeLLM(responses=["- 现货优势文案示例（依据：事实1）"])
    run_id = start_workflow(settings, "scan", {}, background=False, llm=llm)
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done"
        assert "渠道推广文案" in run.result_md
        assert "依据事实" in run.result_md
    assert "规划" in _steps(settings, run_id)


@pytest.mark.skipif(not DECK.exists(), reason="deck not present")
def test_ingest_workflow_queues_profile_facts(settings):
    seed(settings, reset=True)
    profile_json = json.dumps(
        {"positioning": "测试定位声明", "warranty": "三年质保"}, ensure_ascii=False)
    llm = FakeLLM(handler=lambda sys, user, jm: profile_json)
    run_id = start_workflow(settings, "ingest",
                            {"path": str(DECK)}, background=False, llm=llm)
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done"
        assert run.facts_total > 0
        facts = s.exec(select(PendingFact).where(PendingFact.run_id == run_id)).all()
        # LLM single-source profile claims must be pending, not auto-applied.
        assert any(f.status == "pending" for f in facts)
        assert all(f.sources for f in facts)


def test_research_workflow_local_url(settings):
    seed(settings, reset=True)
    products_json = json.dumps({"products": [
        {"product_name": "测试竞品 X1", "price": 2999, "gb_grade": "B",
         "category": "保险柜", "capacity_l": 60},
    ]}, ensure_ascii=False)
    llm = FakeLLM(handler=lambda sys, user, jm: products_json)
    fixture = (FIXTURES / "competitor_v1.html").as_posix()
    run_id = start_workflow(settings, "research",
                            {"brand": "测试品牌", "url": fixture},
                            background=False, llm=llm)
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done", run.error
        assert "品牌深挖报告" in run.result_md
        recs = s.exec(select(ProductRecord).where(
            ProductRecord.company == "测试品牌")).all()
        assert len(recs) == 1
        rec = recs[0]
        facts = s.exec(select(PendingFact).where(PendingFact.run_id == run_id)).all()
        price_fact = next(f for f in facts if f.field == "price")
        # single-source price → pending → price withheld from the record
        assert price_fact.status == "pending"
        assert rec.price is None
    nodes = _steps(settings, run_id)
    for expected in ("规划", "抓取", "抽取", "核查", "评估", "应用"):
        assert expected in nodes


def test_discover_without_search_degrades(settings):
    seed(settings, reset=True)
    run_id = start_workflow(settings, "discover", {"goal": "测试"},
                            background=False, llm=FakeLLM())
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done"
        assert "未配置联网搜索" in run.result_md


# =========================================================================
# Human review (采纳/驳回)
# =========================================================================
def test_review_applies_brand_fact(settings):
    seed(settings, reset=True)
    with session_scope(settings) as s:
        fact = PendingFact(run_id=1, subject="永发 Yongfa", field="positioning",
                           value="新的定位描述", claim="c", sources=["doc#1"],
                           confidence=0.6)
        s.add(fact)
        s.commit()
        s.refresh(fact)
        result = review_fact(s, fact.id, accept=True)
        assert result["status"] == "applied"
        brand = s.exec(select(Brand).where(Brand.name == "永发 Yongfa")).first()
        assert brand.positioning == "新的定位描述"


def test_review_applies_product_price(settings):
    seed(settings, reset=True)
    with session_scope(settings) as s:
        def latest():
            return s.exec(
                select(ProductRecord)
                .where(ProductRecord.product_name == "永发 家用指纹保险柜")
                .order_by(ProductRecord.crawl_time.desc())  # type: ignore[union-attr]
            ).first()

        rec = latest()
        fact = PendingFact(run_id=1, subject=f"{rec.company}|{rec.product_name}",
                           field="price", value="1888", claim="c",
                           sources=["http://x"], confidence=0.6)
        s.add(fact)
        s.commit()
        s.refresh(fact)
        result = review_fact(s, fact.id, accept=True)
        assert result["status"] == "applied"
        assert latest().price == 1888.0   # review updates the LATEST record


def test_review_reject_and_double_review_guard(settings):
    seed(settings, reset=True)
    with session_scope(settings) as s:
        fact = PendingFact(run_id=1, subject="X", field="positioning", value="v",
                           claim="c", sources=["s"], confidence=0.5)
        s.add(fact)
        s.commit()
        s.refresh(fact)
        assert review_fact(s, fact.id, accept=False, note="不实")["status"] == "rejected"
        assert "error" in review_fact(s, fact.id, accept=True)
