# ChubbAgent — ChubbSafes 集宝 China Competitive-Intelligence Pipeline

Internal, scheduled, low-cost competitive-intelligence system for **ChubbSafes China
(集宝, Gunnebo Group)**. It crawls competitor pages, extracts structured product data
with an LLM, computes changes **deterministically**, and generates concise Chinese
reports for the marketing / BI team.

```
Competitor Sources → Fetch → LLM Extract (JSON) → Deterministic Diff → LLM Summary → Store/Export
```

The LLM is used only where it adds value (unstructured→structured extraction, executive
prose). Everything comparable is deterministic, so results are reproducible and cheap.

## Highlights

- **Config-driven sources** — add a competitor by editing `config/sources.yaml`; no code
  change. Static (httpx), local-file, and headless-browser (Playwright) fetchers.
- **Provider-agnostic LLM** — DeepSeek (default) / GLM / Qwen / OpenAI via one
  OpenAI-compatible client; Claude via an Anthropic adapter. Switch = `.env` change.
  Model-tiered: cheap model for high-volume extraction, stronger model for the weekly report.
- **Strict extraction** — JSON mode + Pydantic validation + one repair retry. Bad output
  never poisons a snapshot.
- **Deterministic diff engine** — new / discontinued / price / promotion / spec / stock
  changes, with normalized product matching. Pure and thoroughly unit-tested.
- **Cost controls** — trafilatura main-text extraction, content-hash skip of unchanged
  pages, per-run token/cost logging, off-peak scheduling.
- **Outputs** — SQLite (source of truth) + Excel/CSV + Markdown reports. Google Sheets /
  Notion sinks are stubbed behind the same interface.
- **Dashboard web app** — FastAPI + Jinja2 (server-rendered) enterprise dashboard with
  4 pages (Dashboard / Daily Reports / Competitors / Products), Chart.js visualizations,
  client-side product filtering, CSV export, and a one-click "run crawl" button. Built to
  the provided Stitch design system ("Steel & Navy", IBM Plex Sans + Inter).
- **Runs offline** — `chubb-ci crawl --demo` exercises the whole pipeline with local
  fixtures and no API key; `chubb-ci seed-demo` populates realistic data for the dashboard.

## Quickstart

```bash
# 1. Install (uv). If uv isn't on PATH, use `python -m uv ...`.
uv sync

# 2. Offline demo — no API key needed. Builds a baseline then detects changes.
uv run chubb-ci crawl --demo

# 3. Configure a real provider
cp .env.example .env         # set CHUBB_LLM_API_KEY (DeepSeek by default)

# 4. Initialize + inspect config
uv run chubb-ci init-db
uv run chubb-ci info
uv run chubb-ci list-sources

# 5. One real crawl + daily report (enable a source in config/sources.yaml first)
uv run chubb-ci crawl --kind daily --report

# 6. Run the scheduler (daily digest + weekly report)
uv run chubb-ci serve
```

### Dashboard web app

```bash
uv run chubb-ci seed-demo          # populate realistic demo data (optional)
uv run chubb-ci dashboard          # http://127.0.0.1:8000
```

Pages: **仪表盘** (KPIs + market-insight cards + trend + intelligence feed), **每日报告**
(AI executive summary + price movements + new products), **竞争对手** (directory + per-brand
strategic profile pages from `config/brands.yaml`), **产品情报** (sortable/filterable table
with standardized metrics 容积/防火h/防盗分/元/升/元/公斤/交期 + CSV export), **对标分析**
(head-to-head 对标: price/volume/lead-time deltas, unit costs, 性价比指数), **市场地图**
(capacity×price scatter, capacity-band price matrix with gap detection, brand quadrant),
**促销活动**, **价格变动**, **市场趋势**, and **研究智能体** (Phase 2 preview). The top-bar
**运行抓取** button triggers a live crawl.

### Business-framework data layer

- `chubb_ci/normalize/` — deterministic standardization: fire-rating text → hours,
  GB/EN grades → ordinal 防盗等级分, W×D×H → liters, 元/升·元/公斤·元/小时防火, indexes.
- `chubb_ci/analytics/` — head-to-head 对标 math, capacity-band matrix, and the three
  opportunity rules (|price diff|>5%, band competitors <3, negative 周期差) → `Insight` rows
  regenerated after every crawl and injected into daily/weekly report prompts (facts-only).
- **`chubb-ci load-real`** — build an **all-real dataset** (brands + 集宝 catalog + deck +
  live crawl of every enabled real source), with **no fabricated competitors**. This is the
  default the dashboard should show. (`seed-demo` remains for offline/no-network demos.)
- `chubb-ci sync-brands` — sync `config/brands.yaml` (9 strategic profiles) into the DB.
- `chubb-ci import-catalog ChubbProductsList.xlsx` — import the 集宝 own catalog
  (52 models, 经典/轻奢/防火柜系列) used for benchmarking.
- `chubb-ci ingest-pptx CompetitorAnalysisV7.pptx` — deterministic import of the marketing
  deck's per-brand product tables (24 products / 8 brands: prices, e-commerce sales volumes,
  certifications) as 分析报告-channel records.

### Settings / 系统状态 page

`/settings` shows a **live LLM connectivity check** (green "连接正常" = the API key works),
search-provider status, agent budget, schedule, real-data coverage (products/priced/brands
by source channel), and the full monitored-source list. Insight rules are guarded for
business sanity: pricing anomalies only flag near-peers (5–80% gap, not different tiers),
and capacity-band "market gaps" are suppressed when competitor volume data is unavailable.
- **重点关注 (key competitors)** — star any brand from the 竞争对手 page or its profile
  (`POST /api/brands/{name}/focus`); focused brands sort first with a yellow badge.
  Initial flags come from `focus:` in brands.yaml; UI toggles always win over re-syncs.
- **Working top bar** — global search (`/api/search`: products, competitors, brand
  profiles) and a notifications bell (`/api/notifications`: recent changes + insights).

Ingest the ChubbSafes intro PDF into the domain-context prompt (needs poppler/pdftotext
or `pip install pymupdf`):

```bash
uv run chubb-ci ingest-pdf ./ChubbSafes.pdf
```

## Configuration

All settings come from environment / `.env` (prefix `CHUBB_`) — see `.env.example`.
Sources live in `config/sources.yaml`; domain knowledge in
`config/domain/chubbsafes_context.md`.

Switch LLM provider (example: GLM for a premium weekly report):

```dotenv
CHUBB_LLM_PROVIDER=glm
CHUBB_LLM_API_KEY=your-zhipu-key
CHUBB_LLM_WEEKLY_MODEL=glm-4.6
```

## Architecture

```
chubb_ci/
  config/     settings (env) + sources.yaml loader + domain context
  schemas/    Pydantic wire schema + SQLModel tables
  llm/        provider-agnostic client (deepseek/glm/qwen/openai/anthropic/fake)
  crawler/    fetchers (static/local/browser) + trafilatura cleaning + hashing
  extractor/  schema-guided extraction with JSON repair
  diff/       deterministic diff engine + product matching  (pure)
  summary/    daily digest + weekly report (facts-only, anti-hallucination)
  sinks/      Excel/CSV/Markdown export (+ Sheets/Notion stubs)
  storage/    SQLModel engine + repository (snapshot history)
  scheduler/  APScheduler daily/weekly jobs
  web/        dashboard: FastAPI app + Jinja2 templates + static (Chart.js) + services
  pipeline.py orchestration shared by CLI + scheduler
  cli.py      Typer CLI (crawl / report / serve / dashboard / seed-demo / ingest-pdf)
  demo_seed.py realistic sample data for the dashboard
  agent/      Phase 2 LangGraph discovery agent (scaffold only)
```

Data model: `CrawlRun → Snapshot → ProductRecord`, plus `DiffEvent` and `Report`.
Snapshots are historical; the diff engine compares the newest against the prior baseline.

## Deployment (Docker)

```bash
cp .env.example .env         # set your key
docker compose up --build -d            # runs both the scheduler and the dashboard
# scheduler  → daily/weekly pipelines on cron
# dashboard  → http://localhost:8000
```

Data (SQLite, raw HTML, reports) persists to `./data`; `./config` is mounted so sources
and domain context can change without a rebuild.

For **marketplace** sources (Tmall/JD), enable the browser fetcher:
`uv sync --extra browser && uv run playwright install chromium`. Marketplace anti-bot is
handled best-effort (log + skip, never crash).

## Tests

```bash
uv run pytest
```

Covers the diff engine, schema validation, the extraction repair loop, the Excel sink,
and a full offline pipeline run.

## Research agent (Phase C — live)

Four workflows, runnable from the CLI (`chubb-ci agent …`) or the **研究智能体** page
(launch buttons + real-time run log + review queue):

| Workflow | Command | What it does |
|---|---|---|
| 机会扫描 | `chubb-ci agent scan` | Recompute 对标/capacity analytics → LLM drafts 渠道推广文案, every line cites its fact |
| 文档摄取 | `chubb-ci agent ingest <pptx/pdf>` | Deterministic product tables → DB; LLM-extracted brand-profile claims → 真实性核查 → human review queue |
| 品牌深挖 | `chubb-ci agent research <brand> [--url]` | LangGraph loop: search→fetch→extract→verify→evaluate; verified fields enter the DB, unverified are withheld + queued |
| 竞品发现 | `chubb-ci agent discover [goal]` | Find untracked brands; candidates queue for approval (accepted → focused Brand stub). Needs `CHUBB_SEARCH_PROVIDER=bocha` + key |

Safety properties: **bounded execution** (`AgentBudget`: max iterations/cost/time, enforced
every evaluate step), **provenance-first** (`SourcedFact` — no source, no entry), the
**Verify node** (multi-source corroboration + normalize-based consistency checks; low
confidence → human 采纳/驳回 via `POST /api/agent/facts/{id}/review`), and a **live run log**
streamed over **SSE** (`GET /api/agent/runs/{id}/stream`: `step`/`status`/`done` events;
works for CLI-launched runs too, with automatic polling fallback in old browsers).

## Marketplace price crawling (Playwright)

```bash
uv sync --extra browser
uv run playwright install chromium chromium-headless-shell
```

> **Gotcha:** if crawls suddenly fail with *"Executable doesn't exist"*, a Playwright
> upgrade changed the required browser build — just re-run the `playwright install` line.
> That (not site blocking) is the usual cause of marketplace sources erroring.

**"0 changes" is normal on a first crawl.** Change detection is time-based: the diff
engine compares a source against its previous snapshot. A first/baseline crawl (or right
after `load-real`, which resets) has nothing to compare against → 0 changes. Unchanged
pages are skipped by content hash. Changes appear when a source is re-crawled *after* a
real price/stock/promo move. The crawl summary now reports this explicitly:
`抓取成功 N（其中首次基线 B）· 内容未变跳过 S · 被拦截 X · 检测到 C 处变化`.

Field findings (2026-07): **JD search/mobile now force a login wall** (kept as a disabled
template pending an enterprise-cookie approach); **苏宁 search pages render full price
tiles** after lazy-load scrolling. Live 苏宁 sources for the brands Suning actually carries (得力/艾谱/甬康达/虎王/驰球)
pull real SKUs+prices daily; the extraction prompt keeps only products belonging to the
source's brand (search pages mix brands). Anti-bot challenges are
detected and skipped gracefully (`status=blocked`), never crashing the pipeline.
