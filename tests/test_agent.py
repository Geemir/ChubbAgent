"""Tests for the Phase C agent: verify node, workflows (FakeLLM), and human review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select

from chubb_ci.agent.service import review_fact, start_workflow
from chubb_ci.agent.state import SearchHit, SourcedFact
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


def test_unknown_workflow_rejected(settings):
    import pytest as _pytest

    with _pytest.raises(ValueError):
        start_workflow(settings, "scan", {}, background=False, llm=FakeLLM())


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


def test_enrich_workflow_fills_only_verified_missing_fields(settings):
    """Two independent source URLs corroborate numeric specs; existing data is preserved."""
    seed(settings, reset=True)
    products_json = json.dumps({"products": [
        {"product_name": "测试竞品 X1", "capacity_l": 60, "weight_kg": 52,
         "width_mm": 400, "depth_mm": 350, "height_mm": 500,
         "category": "不应覆盖已有品类", "key_features": ["电子锁"]},
    ]}, ensure_ascii=False)
    llm = FakeLLM(handler=lambda sys, user, jm: products_json)
    with session_scope(settings) as s:
        rec = ProductRecord(
            company="测试品牌", product_name="测试竞品 X1", product_key="测试竞品x1",
            category="保险柜", fire_hours=1.5, security_score=2,
            product_url=(FIXTURES / "competitor_v1.html").as_posix(),
            source_url=(FIXTURES / "competitor_v2.html").as_posix(),
        )
        s.add(rec)
        s.commit()
        s.refresh(rec)
        product_id = rec.id

    run_id = start_workflow(settings, "enrich", {"product_id": product_id},
                            background=False, llm=llm)
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        rec = s.get(ProductRecord, product_id)
        assert run.status == "done", run.error
        assert run.facts_verified >= 5
        assert rec.capacity_l == 60
        assert rec.weight_kg == 52
        assert rec.width_mm == 400 and rec.depth_mm == 350 and rec.height_mm == 500
        assert rec.category == "保险柜"  # enrichment never overwrites non-empty values
        assert rec.fire_hours == 1.5 and rec.security_score == 2
        facts = s.exec(select(PendingFact).where(PendingFact.run_id == run_id)).all()
        assert any(f.status == "applied" for f in facts)
        assert any(f.field == "key_features" and f.status == "pending" for f in facts)

    nodes = _steps(settings, run_id)
    for expected in ("规划", "抓取", "抽取", "核查", "应用"):
        assert expected in nodes


class _FakeSearch:
    """Injectable web-search stub for sentiment tests (no network)."""

    available = True

    def __init__(self, hits):
        self._hits = hits

    def search(self, query, *, top_k=10):
        return list(self._hits)[:top_k]


def test_sentiment_without_search_degrades(settings):
    seed(settings, reset=True)
    run_id = start_workflow(settings, "sentiment", {"goal": "集宝"},
                            background=False, llm=FakeLLM())
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done"
        assert "未配置联网搜索" in run.result_md


def test_sentiment_classifies_and_reports(settings):
    seed(settings, reset=True)
    hits = [SearchHit(title="集宝保险柜好用吗", url="https://a.example/1",
                      snippet="做工扎实，认证齐全，值得买"),
            SearchHit(title="集宝售后吐槽", url="https://b.example/2",
                      snippet="客服响应慢，物流一般")]
    # 1st LLM call = classification JSON; 2nd = the prose report.
    classify = json.dumps({"items": [
        {"idx": 0, "sentiment": "正面", "theme": "品质", "point": "做工扎实"},
        {"idx": 1, "sentiment": "负面", "theme": "售后", "point": "客服慢"},
    ]}, ensure_ascii=False)
    llm = FakeLLM(responses=[classify, "## 舆情概览\n正面为主，售后需改进。[1]"])
    run_id = start_workflow(settings, "sentiment", {"goal": "集宝 ChubbSafes"},
                            background=False, llm=llm, search=_FakeSearch(hits))
    with session_scope(settings) as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "done", run.error
        assert "舆情分析报告" in run.result_md
        # deterministic tally traces to the two classified sources
        assert "正面 1" in run.result_md and "负面 1" in run.result_md
        assert "https://a.example/1" in run.result_md  # sources cited
    nodes = _steps(settings, run_id)
    for expected in ("规划", "搜索", "分析", "汇总"):
        assert expected in nodes


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
