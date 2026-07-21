# ChubbAgent — ChubbSafes 集宝 competitive-intelligence dashboard

An internal tool for the **ChubbSafes China (集宝, Gunnebo)** marketing / BI team. It
collects competitor product data (official brand sites + online marketplaces + the analysis
deck), standardizes and compares it **deterministically**, and presents everything in a
web dashboard. An LLM is used only where it helps (turning messy pages into structured data
and writing the report prose); every number you compare is computed by code, so results are
reproducible and cheap.

```
Competitor sources → fetch → extract → standardize → compare → dashboard + reports
```

---

## For the marketing team — everything runs in the dashboard

**Day to day you never need the command line.** Open the dashboard in a browser and use the
buttons. The person who installs it (below) only does that once.

Start it (or ask IT to keep it running):

```bash
py -m uv run chubb-ci dashboard --port 8010     # then open http://127.0.0.1:8010
```

### The one button that matters: 运行抓取

Top-right of every page. Click it to **refresh the daily data now** — it re-crawls the daily
sources (marketplace prices, promotions, stock), detects changes, and regenerates the daily
report. A toast tells you how many changes were found, then the page reloads. (It also runs
automatically on a daily schedule when the server is left running.)

The **official-site product catalogs** (艾谱 / 福美德 / 迪堡 / 永发 / ZOL) are heavier and
change rarely, so they refresh on the **weekly** run, not this button. To pull everything
fresh on demand, run `chubb-ci load-real` (or `chubb-ci crawl --kind weekly`).

### The pages

| Page | What you use it for |
|---|---|
| **仪表盘** Dashboard | KPIs, market-insight cards, change trend, live intelligence feed |
| **每日报告** Daily report | AI executive summary + today's price moves + new products |
| **竞争对手** Competitors | Brand directory + per-brand strategic profiles. ⭐ any brand to mark it **重点关注** (sorts first) |
| **产品情报** Products | Full product table with photos, filters (brand / channel / category), standardized metrics (容积 / 防火h / 防盗分 / 元每升), and **CSV export** |
| **多平台比价** Price compare | Same model's price side-by-side across 京东 / 天猫 / 苏宁, with lowest price + spread % |
| **对标分析** Benchmark | Head-to-head 集宝-vs-competitor: price / volume / lead-time deltas, 性价比指数 |
| **市场地图** Market map | Capacity × price scatter, capacity-band price matrix, brand quadrant |
| **促销活动 / 价格变动 / 市场趋势** | Active promotions, recent price changes, trend charts |
| **研究智能体** Research agent | One-click AI workflows (below) with a live run log and an 采纳/驳回 review queue |
| **系统状态** Settings | Is the AI key working? data coverage by source, the full source list, schedule |

Top bar also has **global search** (products / competitors / brands) and a **notifications**
bell (recent changes + insights).

### AI workflows (研究智能体 page — just click)

- **机会扫描** — recompute the analytics and let the AI draft 渠道推广文案, every line citing the fact it came from.
- **文档摄取** — upload the marketing deck (PPTX) or a PDF; product tables load automatically, and the AI's brand claims go to a review queue for you to 采纳/驳回.
- **品牌深挖** — pick a brand; the agent searches, reads, and **fact-checks** before anything enters the database.
- **竞品信息自动化搜集** — pick a product; the agent browses its saved links + searches to fill only the empty spec fields, verified across sources.
- **舆情分析** — searches the web for content about ChubbSafes/集宝 (or any topic), classifies each source's sentiment, and writes a cited 舆情 report (needs a search key configured).

Nothing the AI finds is trusted blindly: unverified facts wait in the review queue for a human.

---

## Setup (once, by whoever installs it)

```bash
# 1. Install dependencies (uv). On Windows, uv isn't on PATH → use `py -m uv`.
py -m uv sync
py -m uv run playwright install chromium chromium-headless-shell   # for marketplace/JS sites

# 2. Add the AI key
cp .env.example .env          # set CHUBB_LLM_API_KEY (DeepSeek by default)

# 3. Load real data (brands + 集宝 catalog + analysis deck + live crawl of every source)
py -m uv run chubb-ci load-real

# 4. Start the dashboard
py -m uv run chubb-ci dashboard --port 8010     # http://127.0.0.1:8010
```

Prefer a no-network trial first? `py -m uv run chubb-ci crawl --demo` runs the whole pipeline
on bundled sample pages with no API key.

**One-time logins for JD / 天猫 prices** (optional — 苏宁 and official sites need no login):

```bash
py -m uv run chubb-ci login jd        # opens a browser → scan the QR with the JD app → Enter
py -m uv run chubb-ci login taobao    # for 天猫 / 淘宝
```

The session is saved to `data/sessions/<platform>.json` and reused automatically.

---

## Where the data comes from

| Source | What we get | How |
|---|---|---|
| **Brand official sites** (艾谱 / 福美德 / 迪堡 / 永发 …) | **Full product catalogs** — every model, specs, official photos (no price) | catalog spider (`crawl_catalog`) follows category → detail links |
| **苏宁** | Real prices, sales, photos | works automatically, no login |
| **京东 / 天猫** | Prices, specs, photos | after a one-time QR login (rate-limited — see below) |
| **ZOL 中关村在线** | Cross-brand model list + photos | one aggregated feed |
| **Analysis deck (PPTX)** | Curated competitor prices / sales / certs | 文档摄取 workflow |

Adding a competitor is a **config edit, not code** — a block in
[`config/sources.yaml`](config/sources.yaml). Full source matrix and how to extend:
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

---

## Good to know (please read before handoff)

- **"0 changes" on a fresh crawl is normal.** Change detection compares a source to its
  *previous* snapshot. A first crawl (or right after `load-real`, which resets the data) has
  nothing to compare to → 0 changes. Real changes show up when a source is re-crawled *after*
  a price/stock/promo actually moves.
- **Unchanged pages are skipped** (by content hash) to save cost. Consequence: if you edit a
  source's settings in `sources.yaml` but its page hasn't changed, a re-crawl **won't re-read
  it**. To force a full refresh, run `chubb-ci load-real`.
- **JD is rate-limited by IP**, even when logged in. If a JD crawl comes back "被拦截"
  (blocked), that's JD throttling — wait for it to cool down, or run with a visible browser
  (`CHUBB_BROWSER_HEADLESS=false`), or use a different network. 苏宁 and official sites don't
  have this problem. (The crawler now reports these blocks honestly instead of silently
  recording 0 products.)
- **Official-site catalogs have no prices** — that's expected. Use them for the full product
  line-up and photos; prices come from 苏宁 / 京东 / 天猫.
- **If crawls suddenly fail with "Executable doesn't exist"**, a Playwright update changed the
  required browser build — re-run `py -m uv run playwright install chromium chromium-headless-shell`.
  (This looks like site blocking but isn't.)
- **Windows notes:** run commands as `py -m uv run …`; if Chinese text looks garbled in a
  console, prefix with `PYTHONUTF8=1`. The dashboard uses **port 8010** (8000 can be occupied).
- **AI key not working?** The 系统状态 page shows a live green/red connectivity check.

---

## Configuration

Everything is env-driven (`.env`, prefix `CHUBB_`) — see `.env.example`. Sources live in
`config/sources.yaml`; brand profiles in `config/brands.yaml`; domain knowledge in
`config/domain/chubbsafes_context.md`.

Provider-agnostic LLM — DeepSeek (default) / GLM / Qwen / OpenAI via one OpenAI-compatible
client, or Claude via an Anthropic adapter. Switching is a `.env` change:

```dotenv
CHUBB_LLM_PROVIDER=glm
CHUBB_LLM_API_KEY=your-zhipu-key
CHUBB_LLM_WEEKLY_MODEL=glm-4.6
```

Model-tiered by design: a cheap model on the high-volume extraction path, a stronger model
for the weekly report.

---

## Deployment (Docker)

```bash
cp .env.example .env
docker compose up --build -d       # runs the scheduler + the dashboard
# scheduler → daily digest + weekly report on cron
# dashboard → http://localhost:8000
```

Data (SQLite, raw HTML, reports) persists to `./data`; `./config` is mounted so sources and
domain context can change without a rebuild.

---

## For developers

### Architecture

```
chubb_ci/
  config/     settings (env) + sources.yaml loader + domain context
  schemas/    Pydantic wire schema + SQLModel tables
  llm/        provider-agnostic client (deepseek/glm/qwen/openai/anthropic/fake)
  crawler/    fetchers (static/local/browser) + catalog spider + tile/detail parsers + cleaning
  extractor/  schema-guided LLM extraction with JSON repair
  diff/       deterministic diff engine + product matching (pure)
  normalize/  fire→hours, GB/EN grade→ordinal, W×D×H→liters, unit costs
  analytics/  head-to-head 对标, capacity-band matrix, opportunity rules → Insight rows
  summary/    daily digest + weekly report (facts-only, anti-hallucination)
  storage/    SQLModel engine + repository (snapshot history)
  scheduler/  APScheduler daily/weekly jobs
  web/        dashboard: FastAPI app + Jinja2 templates + static (Chart.js) + services
  agent/      research agent (LangGraph): scan / ingest / research / enrich / sentiment
  pipeline.py orchestration shared by CLI + scheduler
  cli.py      Typer CLI
```

Data model: `CrawlRun → Snapshot → ProductRecord`, plus `DiffEvent`, `Insight`, `Report`.
Snapshots are historical; the diff engine compares the newest against the prior baseline.

Two extraction paths, both deterministic (no LLM): the **catalog spider**
(`crawler/catalog.py`) for official-site product ranges, and the **tile/detail parsers**
(`crawler/tiles.py`, `crawler/detail.py`) for marketplace listings + spec tables. Product
photos are served through a cached, SSRF-guarded **image proxy** (`/api/img`) that adds the
right Referer to dodge hotlink 403s. The research agent is provenance-first: a `SourcedFact`
with no source never enters the DB, and low-confidence facts go to a human review queue; the
run log streams over SSE.

### CLI reference (admin / setup)

| Command | Purpose |
|---|---|
| `chubb-ci load-real` | Rebuild the full real dataset (brands + catalog + deck + live crawl). **Run after changing sources or the schema.** |
| `chubb-ci crawl --kind daily [--report]` | One crawl (all enabled daily sources) |
| `chubb-ci crawl --demo` | Offline pipeline demo, no API key |
| `chubb-ci dashboard [--port 8010]` | Start the web app (defaults to port 8000; use `--port 8010` if 8000 is busy) |
| `chubb-ci serve` | Run the scheduler (daily digest + weekly report) |
| `chubb-ci login <jd\|taobao>` | Save a marketplace session (QR scan) |
| `chubb-ci agent <scan\|ingest\|research\|enrich\|sentiment>` | Research-agent workflows |
| `chubb-ci info` / `list-sources` | Inspect config |

### Tests

```bash
py -m uv run pytest
```

Covers the catalog spider, tile/detail parsers, diff engine, schema validation, the
extraction repair loop, normalization, analytics, the web services/routes, and a full
offline pipeline run.
