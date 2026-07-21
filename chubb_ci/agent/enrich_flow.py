"""Product-specific competitor information collection.

The workflow browses the selected product's stored links plus optional search results,
extracts only fields that are currently blank, verifies claims across sources, and
auto-applies only unambiguous verified facts. Everything else enters the existing human
review queue with source URLs.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from chubb_ci.agent.product_fields import (
    ENRICHABLE_PRODUCT_FIELDS,
    deserialize_fact_value,
    is_missing,
    refresh_computed_fields,
    serialize_fact_value,
)
from chubb_ci.agent.runtime import AgentContext, finish_run
from chubb_ci.agent.state import SourcedFact
from chubb_ci.agent.verify import BASE_LLM, verify_facts
from chubb_ci.config.sources import Source
from chubb_ci.crawler.orchestrator import fetch_and_clean, make_fetcher
from chubb_ci.crawler.session import platform_for_url
from chubb_ci.diff.matching import model_code, normalize_product_key
from chubb_ci.extractor.extractor import extract_products
from chubb_ci.llm.base import LLMClient
from chubb_ci.llm.factory import resolve_model
from chubb_ci.schemas.models import ProductRecord

_MAX_URLS = 4


def _unique_urls(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        url = (value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def _select_product(target: ProductRecord, products: list) -> object | None:
    """Choose the extracted row matching the selected product without an LLM judgment."""
    if not products:
        return None
    target_key = normalize_product_key(target.product_name)
    target_code = target.model_code or model_code(target.product_name)
    for product in products:
        if normalize_product_key(product.product_name) == target_key:
            return product
    if target_code:
        for product in products:
            if model_code(product.product_name) == target_code:
                return product
    # A dedicated product page commonly yields exactly one record; accepting that row is
    # safer than fuzzy matching across a multi-product listing.
    return products[0] if len(products) == 1 else None


def _search_urls(ctx: AgentContext, search, target: ProductRecord) -> list[str]:
    if not getattr(search, "available", False):
        ctx.log("搜索", "未配置搜索服务；仅浏览产品已保存的来源链接")
        return []
    code = target.model_code or model_code(target.product_name) or target.product_name
    queries = [
        f"{target.company} {code} 参数 规格",
        f"{target.company} {code} 价格 容量 重量",
    ]
    urls: list[str] = []
    for query in queries:
        hits = search.search(query, top_k=5)
        ctx.log("搜索", f"检索「{query}」→ {len(hits)} 条结果")
        urls.extend(hit.url for hit in hits if hit.url)
    return urls


def _fetcher_kind(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "local"
    return "browser" if platform_for_url(url) else "static"


def _collect_facts(ctx: AgentContext, llm: LLMClient, target: ProductRecord,
                   urls: list[str], missing_fields: list[str]) -> tuple[list[SourcedFact], list[str]]:
    facts: list[SourcedFact] = []
    visited: list[str] = []
    subject = f"{target.company}|{target.product_name}"
    for url in urls[:_MAX_URLS]:
        ctx.check_budget()
        source = Source(
            name=f"agent-enrich-{target.id}", company=target.company, urls=[url],
            channel="竞品信息自动化搜集", fetcher=_fetcher_kind(url),
        )
        cleaned = fetch_and_clean(make_fetcher(source, ctx.settings), url, ctx.settings)
        visited.append(url)
        ctx.run.iterations += 1
        ctx.session.add(ctx.run)
        ctx.session.commit()
        host = urlparse(url).netloc or "本地来源"
        if not cleaned.fetch.ok or not cleaned.main_text:
            ctx.log("抓取", f"抓取失败 {host}（{cleaned.fetch.error or '无正文'}）", url)
            continue
        ctx.log("抓取", f"抓取 {host} … 正文 {len(cleaned.main_text) / 1000:.1f}k 字", url)
        result = extract_products(
            llm, model=resolve_model(ctx.settings, "extract"), source=source, url=url,
            page_text=cleaned.main_text, domain_context=ctx.settings.load_domain_context(),
        )
        ctx.run.tokens_in += result.tokens_in
        ctx.run.tokens_out += result.tokens_out
        matched = _select_product(target, result.products)
        if matched is None:
            ctx.log("抽取", f"{host}：未找到与「{target.product_name}」确定匹配的产品")
            continue
        found = 0
        for field in missing_fields:
            value = getattr(matched, field, None)
            if is_missing(value):
                continue
            serialized = serialize_fact_value(value)
            facts.append(SourcedFact(
                claim=f"{target.company} {target.product_name} 的 {field}: {serialized}",
                field=field, value=serialized, subject=subject,
                sources=[url], confidence=BASE_LLM,
            ))
            found += 1
        ctx.log("抽取", f"{host}：为目标产品识别出 {found} 项缺失参数")
    return facts, visited


def _apply_verified(ctx: AgentContext, target: ProductRecord,
                    facts: list[SourcedFact]) -> tuple[int, int]:
    """Apply only one unambiguous verified value per still-empty field."""
    verified_by_field: dict[str, list[SourcedFact]] = defaultdict(list)
    for fact in facts:
        if fact.status == "verified":
            verified_by_field[fact.field].append(fact)

    applied_keys: set[tuple[str, str]] = set()
    for field, candidates in verified_by_field.items():
        values = {candidate.value for candidate in candidates}
        if len(values) != 1 or not is_missing(getattr(target, field, None)):
            continue
        fact = candidates[0]
        try:
            setattr(target, field, deserialize_fact_value(field, fact.value))
        except (TypeError, ValueError):
            continue
        applied_keys.add((field, fact.value))

    refresh_computed_fields(target)
    ctx.session.add(target)
    ctx.session.commit()

    pending = 0
    for fact in facts:
        was_applied = (fact.field, fact.value) in applied_keys
        status = "applied" if was_applied else "pending"
        if not was_applied:
            pending += 1
        ctx.add_pending_fact(
            subject=fact.subject, field=fact.field, value=fact.value, claim=fact.claim,
            sources=fact.sources, corroborations=fact.corroborations,
            confidence=fact.confidence, status=status,
        )
    return len(applied_keys), pending


def run_enrich(ctx: AgentContext, llm: LLMClient, search, *, product_id: int) -> None:
    target = ctx.session.get(ProductRecord, product_id)
    if target is None:
        finish_run(ctx, status="failed", error=f"product {product_id} not found")
        return

    missing_fields = [
        field for field in ENRICHABLE_PRODUCT_FIELDS
        if is_missing(getattr(target, field, None))
    ]
    ctx.log("规划", f"自动搜集「{target.product_name}」的 {len(missing_fields)} 项空缺参数",
            "只补空值；已有数据不会覆盖")
    if not missing_fields:
        finish_run(ctx, result_md=f"# 竞品信息自动化搜集\n\n{target.product_name} 当前没有可补充的空字段。")
        return

    stored_urls = _unique_urls([target.product_url, target.source_url])
    searched_urls = _search_urls(ctx, search, target)
    urls = _unique_urls(stored_urls + searched_urls)[:_MAX_URLS]
    if not urls:
        finish_run(ctx, status="failed", error="产品没有可浏览链接，且搜索服务不可用或未返回结果")
        return

    facts, visited = _collect_facts(ctx, llm, target, urls, missing_fields)
    verified = verify_facts(facts, threshold=ctx.settings.agent_verify_threshold)
    checked = verified.verified + verified.pending
    ctx.log("核查", f"核查 {len(checked)} 条声明：{len(verified.verified)} 通过 / "
            f"{len(verified.pending)} 待人工确认", "多源互证 + 确定性一致性校验")
    applied, pending = _apply_verified(ctx, target, checked)
    ctx.run.facts_total = len(checked)
    ctx.run.facts_verified = applied
    ctx.run.facts_pending = pending
    ctx.log("应用", f"已补充 {applied} 项空缺参数；{pending} 条声明进入人工确认队列")

    lines = [
        f"# 竞品信息自动化搜集：{target.product_name}", "",
        f"- 浏览来源：{len(visited)}", f"- 自动补充：{applied} 项",
        f"- 待人工确认：{pending} 条", "", "## 来源", "",
        *[f"- {url}" for url in visited],
    ]
    finish_run(ctx, result_md="\n".join(lines))

