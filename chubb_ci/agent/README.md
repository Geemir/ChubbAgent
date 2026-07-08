# Phase 2 — Intelligent Competitor-Discovery Agent (scaffold)

> **Status: designed, not implemented.** Phase 1 is the production MVP. This package
> holds the interfaces and bounded-loop guards so Phase 2 can be built without
> reshaping Phase 1.

## Goal

Move from *monitoring predefined sources* to *discovering competitors we don't yet
track* — new domestic safe brands, emerging categories, market trends — and recommend
which sites are worth adding to `sources.yaml`.

## Graph

```
Planner → Search → Fetch → Extract → Verify(真实性核查) → Evaluate ──enough?──▶ Final Report
             ▲                                                  │
             └────────────────────── no ───────────────────────┘
```

- **Planner** (LLM): turn the goal into search queries.
- **Search** (`SearchProvider`): China-accessible web search — Bing, Bocha (博查),
  or Zhipu GLM's built-in web-search tool. Pluggable via the protocol in `state.py`.
- **Fetch**: reuse Phase 1 `crawler` (`make_fetcher` / `fetch_and_clean`).
- **Extract**: reuse Phase 1 `extractor` to pull brand/product signals. Every extracted
  claim becomes a `SourcedFact` carrying its source URL(s) — no orphan facts.
- **Verify (真实性核查)** — deterministic-first authenticity check:
  1. *Cross-source corroboration*: the same claim found on ≥2 independent sources
     raises confidence; single-source claims stay low-confidence.
  2. *Consistency checks*: reuse `chubb_ci/normalize` + sanity rules (price within the
     brand's known band, fire-hours parseable, volume consistent with dims).
  3. *LLM contradiction pass* (cheap model): flag claims that contradict the page they
     cite. Facts ≥ threshold → `verified`; the rest stay `pending` for **human review**
     — the dashboard shows each pending fact with its source link and 采纳/驳回 buttons,
     and rejections feed back as `review_note` for the report.
- **Evaluate** (LLM): score candidates on *verified* facts only; decide if coverage
  is sufficient (budget guard checked here every loop).
- **Final Report**: candidate competitors + rationale + suggested `sources.yaml` blocks
  + trend notes + ChubbSafes marketing angles — every figure footnoted with its source.

## Live visualization (研究智能体 page)

Every node appends an `AgentStep` (timestamp, node, human-readable message) to
`AgentState.steps`; steps are persisted incrementally so the dashboard's run-log panel
can poll (or SSE-stream) and show, in plain text, exactly what the agent is doing:

```
14:02:01 [规划] 目标拆解为 3 组检索词：保险柜 新品牌 2026 / 智能保险柜 厂家 / …
14:02:05 [搜索] 博查检索「智能保险柜 厂家」→ 10 条结果
14:02:11 [抓取] 抓取 example-safe.cn/products …正文 4.2k 字
14:02:19 [抽取] 识别出 3 款产品（含价格 2 条）
14:02:23 [核查] 「X1 售价 ¥2,999」在 2 个来源一致 → 置信 0.9 ✓；「防火2h」仅 1 来源 → 待人工确认
14:02:30 [评估] 覆盖度不足（1/3 品牌有数据），继续第 2 轮（预算剩余 ¥3.2）
```

## Bounded execution (never loops forever)

`AgentBudget` enforces hard caps checked at every Evaluate step:
`max_iterations`, `max_depth`, `max_cost_cny`, `max_seconds`.

## Why GLM is attractive here

GLM (Zhipu) has native tool-use and a built-in web-search tool that is reachable from
within China, which simplifies the Search node. The `LLMClient` abstraction means the
Planner/Evaluate LLM is swappable independently of the search backend.

## To implement

1. `uv add langgraph`.
2. Implement a concrete `SearchProvider`.
3. Fill in the nodes in `graph.py` reusing Phase 1 modules; compile with checkpointing.
4. Add a `chubb-ci discover "<goal>"` CLI command.
