"""舆情分析 (public-opinion / sentiment analysis) workflow.

Web-searches for content about ChubbSafes/集宝 (or a user-supplied topic), has the LLM
classify each result's sentiment with its source, tallies the counts **deterministically**
(user-visible numbers trace to sourced records), then writes a cited analysis report.

Requires a web-search backend (``CHUBB_SEARCH_PROVIDER=bocha`` + key); degrades gracefully
with setup instructions when none is configured. Search results are UNTRUSTED data — used
only as analysis input, never as instructions.
"""

from __future__ import annotations

import json
from collections import Counter
from urllib.parse import urlparse

from chubb_ci.agent.runtime import AgentContext, finish_run
from chubb_ci.agent.state import SearchHit
from chubb_ci.llm.base import LLMClient
from chubb_ci.llm.factory import resolve_model

DEFAULT_TOPIC = "集宝 ChubbSafes 保险柜"
_MAX_HITS = 24

_SENTIMENTS = ("正面", "中性", "负面")

_CLASSIFY_SYSTEM = """你是舆情分析助手。下面是关于某品牌的搜索结果（标题 | URL | 摘要）。
对**每一条**判断其对该品牌的情感倾向，并抽取一句关键观点。只输出 JSON：
{"items":[{"idx":序号,"sentiment":"正面|中性|负面","theme":"主题标签","point":"一句关键观点"}]}
严格依据摘要判断，不要臆造；无法判断时 sentiment 填「中性」。只输出 JSON。"""

_REPORT_SYSTEM = """你是资深品牌舆情分析师。依据给定的【已分类的搜索结果】撰写一份中文舆情分析报告，
面向市场团队。要求：完全忠于所给材料，不得编造数据或来源；每个结论尽量标注其来源序号 [n]。
结构：\n## 舆情概览\n## 正面评价\n## 负面/风险信号\n## 竞品与对比提及\n## 建议行动
语气客观、精炼。"""


def _queries(topic: str) -> list[str]:
    return [
        f"{topic} 怎么样 评价",
        f"{topic} 口碑 优点 缺点",
        f"{topic} 新闻 报道",
        f"{topic} 投诉 售后 问题",
    ]


def _gather_hits(ctx: AgentContext, search, topic: str) -> list[SearchHit]:
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for q in _queries(topic):
        ctx.check_budget()
        res = search.search(q, top_k=6)
        ctx.log("搜索", f"检索「{q}」→ {len(res)} 条结果")
        for h in res:
            if h.url and h.url not in seen:
                seen.add(h.url)
                hits.append(h)
    return hits[:_MAX_HITS]


def _classify(ctx: AgentContext, llm: LLMClient, hits: list[SearchHit]) -> list[dict]:
    block = "\n".join(
        f"{i}. {h.title} | {h.url} | {h.snippet[:160]}" for i, h in enumerate(hits))
    try:
        resp = ctx.track(llm.complete(
            system=_CLASSIFY_SYSTEM, user=block,
            model=resolve_model(ctx.settings, "extract"), json_mode=True))
        start, end = resp.content.find("{"), resp.content.rfind("}")
        raw = json.loads(resp.content[start:end + 1]).get("items", [])
    except Exception as exc:  # noqa: BLE001 - never crash on malformed model output
        ctx.log("分析", f"情感分类解析失败：{exc}")
        return []
    items: list[dict] = []
    for it in raw:
        idx = it.get("idx")
        if not isinstance(idx, int) or not (0 <= idx < len(hits)):
            continue
        sentiment = it.get("sentiment") if it.get("sentiment") in _SENTIMENTS else "中性"
        items.append({
            "url": hits[idx].url, "title": hits[idx].title,
            "sentiment": sentiment, "theme": (it.get("theme") or "").strip(),
            "point": (it.get("point") or "").strip(),
        })
    return items


def _report(ctx: AgentContext, llm: LLMClient, topic: str,
            items: list[dict], tally: Counter) -> str:
    total = len(items)
    header = [
        f"# 舆情分析报告：{topic}", "",
        f"- 有效来源：{total} 条",
        f"- 情感分布：正面 {tally['正面']} · 中性 {tally['中性']} · 负面 {tally['负面']}",
        "",
    ]
    if not items:
        return "\n".join(header + ["（本轮未获取到可分析的舆情内容。）"])

    classified = "\n".join(
        f"{i}. [{it['sentiment']}] {it['theme']}：{it['point']}（来源 {it['url']}）"
        for i, it in enumerate(items))
    user = (f"品牌/话题：{topic}\n情感统计：正面{tally['正面']}/中性{tally['中性']}/"
            f"负面{tally['负面']}\n\n已分类的搜索结果：\n{classified}")
    try:
        resp = ctx.track(llm.complete(
            system=_REPORT_SYSTEM, user=user,
            model=resolve_model(ctx.settings, "daily")))
        body = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        ctx.log("汇总", f"报告生成失败，回退为要点列表：{exc}")
        body = "\n".join(f"- [{it['sentiment']}] {it['point']}（{it['url']}）"
                         for it in items)

    sources = ["", "## 来源清单", ""] + [
        f"{i}. [{it['sentiment']}] {it['title'] or urlparse(it['url']).netloc} — {it['url']}"
        for i, it in enumerate(items)]
    return "\n".join(header + [body] + sources)


def run_sentiment(ctx: AgentContext, llm: LLMClient, search, *, goal: str = "") -> None:
    topic = (goal or "").strip() or DEFAULT_TOPIC
    ctx.log("规划", f"舆情分析目标：{topic}", "联网检索 → 情感分类 → 生成分析报告")

    if not getattr(search, "available", False):
        finish_run(ctx, status="done", result_md=(
            f"# 舆情分析：{topic}\n\n未配置联网搜索服务，无法执行舆情分析。\n\n"
            "在 `.env` 中配置后重试：\n```\nCHUBB_SEARCH_PROVIDER=bocha\n"
            "CHUBB_SEARCH_API_KEY=你的博查APIKey\n```\n"
            "（博查 api.bochaai.com 为国内可直连的搜索 API，按量计费。）"))
        return

    hits = _gather_hits(ctx, search, topic)
    ctx.run.iterations = 1
    if not hits:
        ctx.log("分析", "未检索到相关内容")
        finish_run(ctx, result_md=f"# 舆情分析报告：{topic}\n\n本轮未检索到相关舆情内容。")
        return

    items = _classify(ctx, llm, hits)
    tally: Counter = Counter({s: 0 for s in _SENTIMENTS})
    tally.update(it["sentiment"] for it in items)
    ctx.log("分析", f"完成 {len(items)} 条情感分类："
            f"正面 {tally['正面']} / 中性 {tally['中性']} / 负面 {tally['负面']}")

    report = _report(ctx, llm, topic, items, tally)
    ctx.log("汇总", "已生成舆情分析报告")
    finish_run(ctx, result_md=report)
