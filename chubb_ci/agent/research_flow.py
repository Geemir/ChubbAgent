"""C2/C4 — LangGraph flows: brand deep-dive research & competitor discovery.

Graph (research):
    plan → search → fetch → extract → verify → evaluate ──continue──▶ search
                                                 └───────finish────▶ finalize

Every node is a closure over the :class:`AgentContext` (session/logger/budget) and
appends live-log lines. All Phase-1 machinery is reused as tools: crawler fetchers,
LLM extractor, normalize, verify. The budget guard is enforced in `evaluate`; the
graph can never loop past ``AgentBudget``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from chubb_ci.agent.runtime import AgentContext, BudgetExceeded, finish_run
from chubb_ci.agent.state import SearchHit, SourcedFact
from chubb_ci.agent.verify import BASE_LLM, verify_facts
from chubb_ci.config.sources import Source
from chubb_ci.crawler.orchestrator import fetch_and_clean, make_fetcher
from chubb_ci.diff.matching import normalize_product_key
from chubb_ci.extractor.extractor import extract_products
from chubb_ci.llm.base import LLMClient, LLMError
from chubb_ci.llm.factory import resolve_model
from chubb_ci.schemas.models import ProductRecord, Snapshot, SnapshotStatus
from chubb_ci.storage.repositories import Repository

_MAX_URLS_PER_ROUND = 3
_CRITICAL_FIELDS = ("price", "fire_rating", "euro_grade", "gb_grade")


class ResearchState(BaseModel):
    goal: str = ""
    brand: str = ""
    mode: str = "research"                 # research | discover
    queries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)          # queue to fetch
    visited: list[str] = Field(default_factory=list)
    pages: dict[str, str] = Field(default_factory=dict)    # url -> main text
    products: list[dict] = Field(default_factory=list)     # extracted product dicts
    facts: list[SourcedFact] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)   # discovery hits
    next_action: str = "continue"
    stop_reason: str = ""


# =========================================================================
# Research flow
# =========================================================================
def build_research_graph(ctx: AgentContext, llm: LLMClient, search) -> StateGraph:
    settings = ctx.settings
    repo = Repository(ctx.session)

    def plan(state: ResearchState) -> dict:
        if state.urls:
            ctx.log("规划", f"使用指定 URL（{len(state.urls)} 个），跳过检索")
            return {"queries": []}
        queries = [
            f"{state.brand} 保险柜 官网 产品",
            f"{state.brand} 保险柜 价格 型号",
        ]
        ctx.log("规划", f"目标拆解为 {len(queries)} 组检索词", " / ".join(queries))
        return {"queries": queries}

    def do_search(state: ResearchState) -> dict:
        if state.urls or not state.queries:
            return {}
        if not getattr(search, "available", False):
            ctx.log("搜索", "未配置搜索服务（CHUBB_SEARCH_PROVIDER），无法联网检索",
                    "研究模式可改用 --url 指定页面")
            return {"next_action": "finish", "stop_reason": "无搜索服务且未提供 URL"}
        found: list[str] = []
        for q in state.queries:
            hits = search.search(q, top_k=5)
            ctx.log("搜索", f"检索「{q}」→ {len(hits)} 条结果")
            found += [h.url for h in hits if h.url]
        # de-dupe by domain, skip visited
        seen_domains, urls = set(), []
        for u in found:
            d = urlparse(u).netloc
            if u in state.visited or d in seen_domains:
                continue
            seen_domains.add(d)
            urls.append(u)
        return {"urls": urls[:_MAX_URLS_PER_ROUND], "queries": []}

    def fetch(state: ResearchState) -> dict:
        pages = dict(state.pages)
        visited = list(state.visited)
        for url in state.urls[:_MAX_URLS_PER_ROUND]:
            # Non-http "URLs" are treated as saved local pages (offline research).
            kind = "static" if url.startswith("http") else "local"
            src = Source(name="agent-research", company=state.brand or "research",
                         urls=[url], channel="智能体研究", fetcher=kind)
            fetcher = make_fetcher(src, settings)
            cleaned = fetch_and_clean(fetcher, url, settings)
            visited.append(url)
            if cleaned.fetch.ok and cleaned.main_text:
                pages[url] = cleaned.main_text
                ctx.log("抓取", f"抓取 {urlparse(url).netloc} … 正文 {len(cleaned.main_text)/1000:.1f}k 字", url)
            else:
                ctx.log("抓取", f"抓取失败 {urlparse(url).netloc}（{cleaned.fetch.error or 'blocked'}）", url)
        return {"pages": pages, "visited": visited, "urls": []}

    def extract(state: ResearchState) -> dict:
        products = list(state.products)
        facts = list(state.facts)
        done_urls = {p.get("_source") for p in products}
        for url, text in state.pages.items():
            if url in done_urls:
                continue
            src = Source(name="agent-research", company=state.brand, urls=[url],
                         channel="智能体研究")
            result = extract_products(
                llm, model=resolve_model(settings, "extract"), source=src, url=url,
                page_text=text, domain_context=settings.load_domain_context())
            ctx.run.tokens_in += result.tokens_in
            ctx.run.tokens_out += result.tokens_out
            ctx.log("抽取", f"{urlparse(url).netloc}：识别出 {len(result.products)} 款产品"
                    + ("" if result.ok else f"（失败：{result.error}）"))
            for p in result.products:
                d = p.model_dump()
                d["_source"] = url
                products.append(d)
                for field in _CRITICAL_FIELDS:
                    value = d.get(field)
                    if value is not None:
                        facts.append(SourcedFact(
                            claim=f"{state.brand} {d['product_name']} 的 {field}: {value}",
                            field=field, value=str(value),
                            subject=f"{state.brand}|{d['product_name']}",
                            sources=[url], confidence=BASE_LLM,
                        ))
        return {"products": products, "facts": facts}

    def verify(state: ResearchState) -> dict:
        if not state.facts:
            return {}
        # Known price band from data already in the DB for this brand.
        prices = [p.price for p in repo.all_products()
                  if p.company == state.brand and p.price]
        bands = ({(f"{state.brand}|{p['product_name']}").lower(): (min(prices), max(prices))
                  for p in state.products} if prices else {})
        vr = verify_facts(state.facts, threshold=settings.agent_verify_threshold,
                          known_price_bands=bands)
        ctx.log("核查", f"核查 {len(state.facts)} 条声明：{len(vr.verified)} 通过 / "
                f"{len(vr.pending)} 待人工确认",
                "多源互证 + 价格带一致性校验")
        return {"facts": vr.verified + vr.pending}

    def evaluate(state: ResearchState) -> dict:
        ctx.run.iterations += 1
        ctx.session.add(ctx.run)
        ctx.session.commit()
        try:
            ctx.check_budget()
        except BudgetExceeded as exc:
            ctx.log("评估", f"预算触顶，结束研究（{exc}）")
            return {"next_action": "finish", "stop_reason": str(exc)}
        priced = sum(1 for p in state.products if p.get("price"))
        if state.products and (priced or ctx.run.iterations >= 2):
            ctx.log("评估", f"已获得 {len(state.products)} 款产品（含价格 {priced} 款），信息充分")
            return {"next_action": "finish", "stop_reason": "covered"}
        if state.next_action == "finish":
            return {}
        if not getattr(search, "available", False):
            ctx.log("评估", "无更多可抓取来源，结束")
            return {"next_action": "finish", "stop_reason": "no more sources"}
        ctx.log("评估", f"覆盖不足（{len(state.products)} 款产品），继续下一轮检索",
                f"预算剩余 ¥{ctx.budget.max_cost_cny - ctx.run.cost_cny:.2f}")
        return {"queries": [f"{state.brand} 保险柜 参数 规格 电商"], "next_action": "continue"}

    def finalize(state: ResearchState) -> dict:
        applied = _apply_products(ctx, state)
        report = _research_report(ctx, llm, state, applied)
        finish_run(ctx, result_md=report)
        return {}

    g = StateGraph(ResearchState)
    g.add_node("plan", plan)
    g.add_node("search", do_search)
    g.add_node("fetch", fetch)
    g.add_node("extract", extract)
    g.add_node("verify", verify)
    g.add_node("evaluate", evaluate)
    g.add_node("finalize", finalize)
    g.set_entry_point("plan")
    g.add_edge("plan", "search")
    g.add_edge("search", "fetch")
    g.add_edge("fetch", "extract")
    g.add_edge("extract", "verify")
    g.add_edge("verify", "evaluate")
    g.add_conditional_edges("evaluate", lambda s: s.next_action,
                            {"continue": "search", "finish": "finalize"})
    g.add_edge("finalize", END)
    return g


def _apply_products(ctx: AgentContext, state: ResearchState) -> int:
    """Persist verified products; unverified critical fields are withheld + queued."""
    verified_keys = {(f.subject.lower(), f.field) for f in state.facts
                     if f.status == "verified"}
    pending = [f for f in state.facts if f.status != "verified"]

    for f in state.facts:
        ctx.add_pending_fact(
            subject=f.subject, field=f.field, value=f.value, claim=f.claim,
            sources=f.sources, corroborations=f.corroborations,
            confidence=f.confidence, status=f.status)
    ctx.run.facts_total = len(state.facts)
    ctx.run.facts_verified = len(state.facts) - len(pending)
    ctx.run.facts_pending = len(pending)

    if not state.products:
        return 0
    now = datetime.now(timezone.utc)
    snap = Snapshot(
        source_name=f"agent-{normalize_product_key(state.brand or state.goal)}",
        company=state.brand, url=state.visited[0] if state.visited else "",
        page_type="product", channel="智能体研究",
        status=SnapshotStatus.OK.value, crawl_time=now, num_products=len(state.products))
    ctx.session.add(snap)
    ctx.session.commit()
    ctx.session.refresh(snap)

    from chubb_ci.normalize import fire_hours, security_score

    applied = 0
    for d in state.products:
        subject = f"{state.brand}|{d['product_name']}".lower()
        record = ProductRecord(
            snapshot_id=snap.id, source_name=snap.source_name, company=state.brand,
            product_name=d["product_name"],
            product_key=normalize_product_key(d["product_name"]),
            category=d.get("category"), currency=d.get("currency") or "CNY",
            capacity_l=d.get("capacity_l"), weight_kg=d.get("weight_kg"),
            lock_type=d.get("lock_type"), key_features=d.get("key_features") or [],
            source_url=d.get("_source"), crawl_time=now)
        # Only verified critical fields enter the DB.
        for field in _CRITICAL_FIELDS:
            if d.get(field) is not None and (subject, field) in verified_keys:
                setattr(record, field, d[field])
        record.fire_hours = fire_hours(record.fire_rating)
        record.security_score = security_score(record.gb_grade, record.euro_grade)
        ctx.session.add(record)
        applied += 1
    ctx.session.commit()
    ctx.log("应用", f"已入库 {applied} 款产品（未核实字段暂缓写入，待人工确认）")
    return applied


def _research_report(ctx: AgentContext, llm: LLMClient, state: ResearchState,
                     applied: int) -> str:
    lines = [f"# 品牌深挖报告：{state.brand or state.goal}", "",
             f"- 抓取页面：{len(state.visited)}（成功 {len(state.pages)}）",
             f"- 识别产品：{len(state.products)} 款（已入库 {applied}）",
             f"- 声明核查：{ctx.run.facts_verified} 通过 / {ctx.run.facts_pending} 待人工",
             f"- 结束原因：{state.stop_reason}", "", "## 来源", ""]
    lines += [f"- {u}" for u in state.visited]
    if state.products:
        lines += ["", "## 识别出的产品", ""]
        for d in state.products[:15]:
            price = f"¥{d['price']}" if d.get("price") else "价格待确认"
            lines.append(f"- {d['product_name']}（{price}）「来源：{d.get('_source','')}」")
    return "\n".join(lines)


def run_research(ctx: AgentContext, llm: LLMClient, search, *,
                 brand: str, url: str | None = None) -> None:
    state = ResearchState(goal=f"深挖品牌 {brand}", brand=brand, mode="research",
                          urls=[url] if url else [])
    graph = build_research_graph(ctx, llm, search).compile()
    try:
        graph.invoke(state, config={"recursion_limit": 60})
    except Exception as exc:  # noqa: BLE001
        ctx.log("评估", f"运行异常终止：{exc}")
        finish_run(ctx, status="failed", error=str(exc))


# =========================================================================
# Discovery flow (C4) — same loop, different extract/finalize
# =========================================================================
_DISCOVER_SYSTEM = """你是竞争情报侦察助手。根据搜索结果（标题/摘要/URL），找出**可能是
保险柜/安全存储品牌或厂商**、且不在已知品牌列表中的候选。只输出 JSON：
{"candidates": [{"name": "品牌名", "url": "官网或店铺URL", "rationale": "判断依据（一句）"}]}
没有候选则输出 {"candidates": []}。严禁编造 URL。"""


def run_discovery(ctx: AgentContext, llm: LLMClient, search, *, goal: str) -> None:
    repo = Repository(ctx.session)
    known = {b.name for b in repo.all_brands()} | {
        p.company for p in repo.all_products()}
    ctx.log("规划", f"发现目标：{goal}", f"已知品牌 {len(known)} 个将被排除")

    if not getattr(search, "available", False):
        ctx.log("搜索", "未配置搜索服务（CHUBB_SEARCH_PROVIDER=bocha + API key），发现模式无法联网",
                "已生成配置说明")
        finish_run(ctx, status="done", result_md=(
            "# 竞品发现\n\n未配置联网搜索服务，无法执行发现任务。\n\n"
            "在 `.env` 中配置：\n```\nCHUBB_SEARCH_PROVIDER=bocha\n"
            "CHUBB_SEARCH_API_KEY=你的博查APIKey\n```\n后重试。"))
        return

    queries = [f"{goal} 保险柜 品牌", "智能保险柜 厂家 新品牌 2026", "家用保险箱 品牌 排行"]
    hits: list[SearchHit] = []
    for q in queries:
        ctx.check_budget()
        res = search.search(q, top_k=8)
        ctx.log("搜索", f"检索「{q}」→ {len(res)} 条结果")
        hits += res
    ctx.run.iterations = 1

    hits_block = "\n".join(f"- {h.title} | {h.url} | {h.snippet[:100]}" for h in hits[:24])
    try:
        resp = ctx.track(llm.complete(
            system=_DISCOVER_SYSTEM,
            user=f"已知品牌（排除）：{('、'.join(sorted(known)))[:800]}\n\n搜索结果：\n{hits_block}",
            model=resolve_model(ctx.settings, "daily"), json_mode=True))
        import json as _json

        start, end = resp.content.find("{"), resp.content.rfind("}")
        candidates = _json.loads(resp.content[start:end + 1]).get("candidates", [])
    except Exception as exc:  # noqa: BLE001
        ctx.log("抽取", f"候选提取失败：{exc}")
        candidates = []
    ctx.log("抽取", f"识别出 {len(candidates)} 个候选新品牌")

    for c in candidates:
        ctx.add_pending_fact(
            subject=c.get("name", "?"), field="discovery",
            value=c.get("url", ""), claim=f"候选新竞品：{c.get('name')}（{c.get('rationale','')}）",
            sources=[c.get("url", "")], confidence=0.5, status="pending")
    ctx.run.facts_total = ctx.run.facts_pending = len(candidates)
    ctx.log("核查", f"{len(candidates)} 个候选进入人工确认队列（采纳后可加入 brands.yaml/sources.yaml）")

    lines = [f"# 竞品发现报告", "", f"目标：{goal}", "", "## 候选品牌", ""]
    for c in candidates:
        lines.append(f"- **{c.get('name')}** — {c.get('url')}\n  - {c.get('rationale','')}")
    if not candidates:
        lines.append("（本轮未发现未跟踪的新品牌）")
    finish_run(ctx, result_md="\n".join(lines))
