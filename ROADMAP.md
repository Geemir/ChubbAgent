# ROADMAP — From Change-Monitoring to Competitive-Analysis Platform

Source: `AnalyzeInformation.md` (internal marketing/product competitive framework).
This maps that business framework onto the existing codebase in three phases.

**Guiding principle (unchanged from Phase 1):** LLM only for unstructured→structured and
prose; everything comparable/computable is **deterministic** (regex, mapping dicts, math).
The business doc explicitly demands this ("standardization rules", "automatic calculation").

---

## Gap analysis — current app vs. business framework

| Business framework (AnalyzeInformation) | Current state | Gap |
|---|---|---|
| Standardized metrics: fire→hours, 防盗等级分, volume from W×D×H | Raw strings (`fire_rating`, `gb_grade`, `euro_grade`), optional `capacity_l` | **No standardization engine** |
| Derivative unit costs: 元/升, 元/公斤, 元/小时防火; 综合指数; 性价比指数 | None | **No analytics module** |
| Own-catalog vs competitor head-to-head (对标), lead-time delta | No own-product data at all | **No own catalog, no counterpart mapping** |
| Brand strategic profiles (positioning, tier, audience, strengths/shortcomings, supply chain, warranty) | Company = a string on sources/products | **No Brand entity** |
| Capacity-band price matrix, capacity×price scatter, quadrant matrices | Generic trend charts | **No market-map visualizations** |
| Opportunity alerts: \|price diff\|>5%, capacity bands with <3 competitors, negative 周期差 → draft copy | Change events only | **No insight/alert engine** |
| Agent: e-commerce scraping, PPTX/brochure parsing, auto metrics, auto charts, copy drafting | Scaffold only (`chubb_ci/agent/`) | **Phase C below** |
| Lead time (订货周期), sales volume, tax price, series, status labels (热卖…) | Not modeled | **Schema fields** |

---

## Phase A — Data & standardization foundation (prerequisite for everything)

### A1. Deterministic normalization engine — `chubb_ci/normalize/`
- `ratings.py`
  - `fire_hours(text) -> float|None` — regex over "UL 1h / UL 90min / 欧标60min / 国标120min / 30分钟" → `1.0, 1.5, 1.0, 2.0, 0.5`
  - `security_score(gb_grade, euro_grade) -> int|None` — ordinal map per the doc:
    `GB A / TL-15 = 1, GB B = 2, GB C = 3, 欧标 S2 = 4, Grade I = 5, II = 6, … V = 9`
- `metrics.py`
  - `volume_l(w_mm, d_mm, h_mm) -> float` (internal dims)
  - `price_per_l`, `price_per_kg`, `price_per_fire_hour`
  - `value_index(product, band_avg)` (综合指数: >1.1 competitive, <0.9 needs repricing)
  - `value_for_money(comp_metric, own_metric)` (性价比指数)
- Pure functions, exhaustively unit-tested (this is the highest-value test surface after diff/).

### A2. Schema extensions (SQLModel + extraction wire schema)
`ExtractedProduct` / `ProductRecord` gain: `width_mm/depth_mm/height_mm` (internal; external
optional), `weight_kg` (exists), `lead_time_days`, `sales_volume`, `tax_price`, `series`,
`status_label` (热卖/价值最高/功能贴近). Ingest pipeline (`pipeline._to_record`) calls the
normalize engine to fill computed columns `fire_hours`, `security_score`, `capacity_l`
(from dims when not stated). LLM never computes these — extraction only captures raw text.

### A3. New entities
- **`Brand`** — strategic profile: positioning, competition_tier, target_audience,
  strengths[], shortcomings[], price_architecture, market_scale, supply_chain, warranty.
  Seeded from **`config/brands.yaml`** — populated immediately with the 6 profiles from
  AnalyzeInformation §6 (百卫特/福美德/艾斐堡/永发/Agresti/B&Z) + 集宝 baseline.
- **`OwnProduct`** — 集宝 catalog with the same parameter schema + `lead_time_days=0`
  (domestic stock advantage). Loaded via `chubb-ci import-catalog <xlsx|csv|yaml>`.
  *Placeholder seed from the ChubbSafes PDF series (欧泊/摩根/塔菲/瑞诺/雅宝…) until the
  real internal price/lead-time spreadsheet is provided — that file is the one hard data
  dependency on the business side.*
- **`CounterpartPair`** — 对标 mapping own_product ↔ competitor product
  (`config/counterparts.yaml`, later agent-suggested).
- **`Insight`** — detected opportunity/anomaly: type (`pricing_anomaly` | `market_gap` |
  `logistics_advantage`), payload JSON, severity, detected_at, run_id.

### A4. Analytics engine — `chubb_ci/analytics/`
- `head_to_head.py` — per counterpart pair: price diff %, volume diff %, lead-time delta
  (负周期差 = our advantage → flag), unit-cost comparison, 性价比指数.
- `capacity_bands.py` — brackets **≤30L / 30–60L / 60–100L / 100–200L / >200L**;
  per band: competitor avg/min/max price, our avg, premium %, sample counts.
- `opportunities.py` — the three doc rules: `|price diff %| > 5%` → pricing_anomaly;
  band competitor count `< 3` → market_gap; negative lead-time delta → logistics_advantage.
- Wired into the pipeline after diff: insights persist, feed the dashboard + reports
  (facts-only → LLM narrates, cannot invent numbers — same anti-hallucination pattern).

---

## Phase B — Webapp features (maps 1:1 to the doc's visualizations)

1. **Brand profile pages** — 竞争对手 cards link to `/competitors/{brand}`: strategic
   profile (positioning/tier/audience/strengths/shortcomings), series & price architecture,
   market scale, supply chain/warranty, plus live crawled products & volatility.
2. **New page 对标分析 `/benchmark`** — head-to-head table over counterpart pairs:
   our model vs competitor, price diff %, volume diff %, 周期差 (negative highlighted in
   Swedish yellow = selling point), unit costs side-by-side, 性价比指数. Detail drawer per pair.
3. **New page 市场地图 `/market-map`** —
   - **容量×价格散点图** (Chart.js scatter): X=volume L, Y=price, color per brand,
     集宝 highlighted; blank capacity bands shaded → "market blank spaces" at a glance.
   - **容量段价格带矩阵** table (band × brand avg/min/max/premium/count).
   - **品牌四象限矩阵** (quadrant scatter): price vs premium-index; certification tier vs
     fire/service score.
4. **产品情报 upgrades** — sortable columns; new standardized columns (容积L, 净重kg,
   防火h, 防盗分, 元/升, 元/公斤, 元/小时防火, 交期天数); status-label chips (热卖 etc.);
   CSV export extended to all metrics.
5. **仪表盘 upgrades** — insight KPI cards (pricing anomalies, market gaps, lead-time
   advantages) + insight items in the intelligence feed.
6. **报告 upgrades** — daily/weekly prompts receive the deterministic insight facts;
   weekly report gains a 对标摘要 section (per the doc: empirical negotiation ammo for
   dealers, not just "what changed").

---

## Phase C — The agent (realizes `chubb_ci/agent/` scaffold, spec from doc §5)

**Architecture:** LangGraph, bounded by the existing `AgentBudget` guards
(max_iterations/depth/cost/time). Nodes call **Phase 1/A modules as tools** — the agent
orchestrates; it never re-implements crawling, extraction, normalization, or math.

**Cross-cutting requirements (from business feedback):**
- **真实性核查 (Verify node)** between Extract and Evaluate: every claim is a `SourcedFact`
  with mandatory source URLs; multi-source corroboration + normalize-based consistency
  checks set confidence; low-confidence facts queue for human 采纳/驳回 review instead of
  entering the DB. Reports footnote every figure with its source.
- **Live activity visualization**: every node appends `AgentStep` log lines (timestamp,
  node, plain-text message) persisted incrementally; the 研究智能体 page shows the run log
  in real time (polling/SSE). See `chubb_ci/agent/state.py` — both models already scaffolded.

**Four workflows (in build order):**
1. **Document ingestion** (`chubb-ci agent ingest <pptx|pdf>`) — parse competitor decks &
   brochures (python-pptx / pdftotext) → LLM-extract brand profile updates + product specs
   → normalize → validated upsert into `Brand`/`ProductRecord` with provenance. *Built
   first: it's how the marketing team's existing PPT knowledge (like the one behind
   AnalyzeInformation) enters the database, and it needs no new network capability.*
2. **Deep-dive product research** (`chubb-ci agent research <brand>`) — search (China-
   accessible provider: Bocha/Bing/Zhipu web-search behind the existing `SearchProvider`
   protocol) → crawl 官网 + marketplace pages (browser fetcher; e-commerce = where prices,
   promos, transaction volumes live) → extract full parameter set → standardize → upsert →
   refresh derivative metrics → suggest counterpart pairs.
3. **Opportunity scan + copy drafting** (`chubb-ci agent scan`, also schedulable weekly) —
   run analytics across the DB → new `Insight`s → LLM drafts **channel marketing copy**
   (渠道推广文案) for each logistics_advantage/anomaly, strictly from computed facts.
4. **Competitor discovery** (original Phase 2 goal) — find untracked brands → propose
   `brands.yaml` profile + `sources.yaml` blocks for human approval.

**Surfaces:** CLI (`chubb-ci agent …`); 研究智能体 page goes live — goal input, streaming
run log (Planner→Search→Fetch→Extract→Evaluate steps), results (new products/insights/
draft copy) with an approve-into-DB step for discovery results.

**Model tiering:** deepseek-chat for tool-loop steps; deepseek-reasoner (or GLM-4.6 later)
for evaluate/synthesize nodes. Costs logged per run in `CrawlRun`-style bookkeeping.

---

## Sequencing & effort

| Step | Contents | Effort | Value unlocked |
|---|---|---|---|
| **A1+A2** | normalize engine, schema fields, ingest wiring | ~1 session | standardized data everywhere |
| **A3+A4** | Brand/OwnProduct/Counterpart/Insight + analytics + brands.yaml seed | ~1 session | head-to-head + opportunity math |
| **B** | 对标分析, 市场地图, brand profiles, table/dashboard/report upgrades | 1–2 sessions | the demo-visible payoff |
| **C1** | agent: document ingestion | ~1 session | PPT/brochure → DB |
| **C2–C4** | research, scan+copy, discovery | 2–3 sessions | full agent |

**Data dependency to request from the business side:** the real 集宝 internal catalog
(model, price, dims, weight, ratings, lead time) — the placeholder own-catalog works for
demos but 对标/指数 numbers only become truthful with the real sheet.

**Deferred consciously:** Playwright marketplace enablement (needed for live price/volume
in C2), PPTX chart *generation* (the doc's matrices are rendered by the webapp instead —
export can come later), Google Sheets/Notion sinks.
