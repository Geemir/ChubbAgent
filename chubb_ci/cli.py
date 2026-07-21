"""Command-line interface (Typer).

    chubb-ci init-db
    chubb-ci list-sources
    chubb-ci crawl [--kind daily|weekly|manual] [--report] [--demo]
    chubb-ci report --daily | --weekly
    chubb-ci serve            # run the APScheduler loop
    chubb-ci ingest-pdf PATH  # PDF -> config/domain/chubbsafes_context.md
    chubb-ci info
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from chubb_ci.config.settings import get_settings
from chubb_ci.config.sources import enabled_sources, load_sources
from chubb_ci.logging_setup import configure_logging


def _force_utf8_io() -> None:
    """Make stdout/stderr UTF-8 so Chinese + symbols print on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - best effort
                pass


_force_utf8_io()

app = typer.Typer(add_completion=False, help="ChubbSafes China competitive-intelligence CLI")
# legacy_windows=False -> emit ANSI to the (UTF-8) stream instead of the GBK win32 API.
console = Console(legacy_windows=False)


@app.callback()
def _init(log_level: str = typer.Option("INFO", "--log-level", help="日志级别")) -> None:
    settings = get_settings()
    configure_logging(level=log_level, log_dir=settings.data_path / "logs")


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the database and tables."""
    from chubb_ci.storage.db import init_db

    settings = get_settings()
    init_db(settings)
    console.print(f"[green]✓[/] database ready at {settings.database_url}")


@app.command("list-sources")
def list_sources_cmd() -> None:
    """List configured sources and their enabled/cadence state."""
    settings = get_settings()
    sources = load_sources(settings.sources_path)
    table = Table(title="监控源 sources.yaml")
    for col in ("name", "company", "enabled", "fetcher", "channel", "freq", "urls"):
        table.add_column(col)
    for s in sources:
        table.add_row(
            s.name, s.company, "✓" if s.enabled else "✗",
            s.fetcher.value, s.channel, s.frequency, str(len(s.urls)),
        )
    console.print(table)
    console.print(f"enabled now: {[s.name for s in enabled_sources(sources)]}")


@app.command("crawl")
def crawl_cmd(
    kind: str = typer.Option("manual", "--kind", help="daily|weekly|manual"),
    frequency: str = typer.Option(None, "--frequency", help="仅抓取该频率的源: daily|weekly"),
    report: bool = typer.Option(False, "--report", help="抓取后生成对应报告"),
    demo: bool = typer.Option(False, "--demo", help="离线演示：用本地样例演示变化检测"),
    provider: str = typer.Option(None, "--provider", help="覆盖 LLM provider（如 fake）"),
) -> None:
    """Run one crawl (fetch → extract → diff → store)."""
    settings = get_settings()
    if provider:
        settings.llm_provider = provider

    from chubb_ci.pipeline import generate_daily, run_crawl

    if demo:
        _run_demo(settings)
        return

    # Default the cadence filter from --kind so `crawl --kind daily` only runs
    # daily-cadence sources (excludes weekly/manual/demo sources).
    freq_filter = frequency or (kind if kind in ("daily", "weekly") else None)
    summary = run_crawl(settings, kind=kind, frequency_filter=freq_filter)
    console.print(
        f"[green]✓[/] run #{summary.run_id}：抓取成功 {summary.sources_ok}"
        f"（其中首次基线 {summary.baselines}）· 内容未变跳过 {summary.sources_skipped}"
        f"· 被拦截 {summary.sources_blocked} · 出错 {summary.sources_failed}"
        f" · 采集 {summary.products_extracted} 款 · [bold]检测到 {summary.events_detected} 处变化[/]"
        f" · 成本≈¥{summary.est_cost_cny}"
    )
    if summary.events_detected == 0 and summary.baselines > 0:
        console.print(
            "[yellow]ℹ[/] 本次多为[bold]首次基线[/]采集，无历史可对比，故 0 变化属正常。"
            "再次抓取（价格/促销/上下架有变动时）即会出现变化。"
        )
    if summary.sources_blocked:
        console.print(f"[yellow]⚠[/] {summary.sources_blocked} 个来源被反爬拦截（已优雅跳过）。")
    if report:
        draft = generate_daily(settings, run_id=summary.run_id)
        console.print(f"[green]✓[/] 报告已生成: {draft.title}")


def _run_demo(settings) -> None:
    """Two crawls over local fixtures (v1 baseline → v2) to show diff detection."""
    from chubb_ci.demo import demo_fake_llm
    from chubb_ci.pipeline import generate_daily, run_crawl

    llm = demo_fake_llm()
    demo_src = ["demo-local-competitor"]
    console.print("[cyan]demo 1/2[/] 建立基线 (competitor_v1)…")
    run_crawl(settings, kind="demo", llm=llm, only_names=demo_src)

    console.print("[cyan]demo 2/2[/] 模拟变化 (competitor_v2)…")
    override = {"tests/fixtures/competitor_v1.html": "tests/fixtures/competitor_v2.html"}
    summary = run_crawl(settings, kind="demo", llm=llm, override_urls=override, only_names=demo_src)
    console.print(
        f"[green]✓[/] 检测到 {summary.events_detected} 处变化 (run #{summary.run_id})"
    )
    # Deterministic digest (no live LLM needed for the offline demo).
    draft = generate_daily(settings, run_id=summary.run_id, use_llm=False)
    console.print(f"\n[bold]{draft.title}[/]\n")
    console.print(draft.content_md)


@app.command("report")
def report_cmd(
    daily: bool = typer.Option(False, "--daily", help="生成每日速报（最近一次抓取）"),
    weekly: bool = typer.Option(False, "--weekly", help="生成每周报告（最近7天）"),
    days: int = typer.Option(7, "--days", help="每周报告回溯天数"),
) -> None:
    """Generate a report from already-stored events."""
    settings = get_settings()
    from chubb_ci.pipeline import generate_daily, generate_weekly

    if not (daily or weekly):
        console.print("[yellow]请指定 --daily 或 --weekly[/]")
        raise typer.Exit(1)

    if daily:
        draft = generate_daily(settings, run_id=_latest_run_id(settings))
        console.print(f"[green]✓[/] {draft.title}")
    if weekly:
        draft = generate_weekly(settings, days=days)
        console.print(f"[green]✓[/] {draft.title}")


def _latest_run_id(settings) -> int | None:
    from sqlmodel import select

    from chubb_ci.schemas.models import CrawlRun
    from chubb_ci.storage.db import session_scope

    with session_scope(settings) as session:
        stmt = select(CrawlRun).order_by(CrawlRun.started_at.desc())  # type: ignore[union-attr]
        run = session.exec(stmt).first()
        return run.id if run else None


@app.command("login")
def login_cmd(
    platform: str = typer.Argument(..., help="平台：jd | taobao | suning | pdd | douyin"),
    timeout: int = typer.Option(180, "--timeout", help="等待登录的最长秒数"),
) -> None:
    """Capture a logged-in marketplace session (QR scan) for authenticated crawling."""
    from chubb_ci.crawler.session import LOGIN_URLS, known_platforms, session_path

    platform = platform.strip().lower()
    if platform not in LOGIN_URLS:
        console.print(f"[red]未知平台[/] '{platform}'。可选：{', '.join(known_platforms())}")
        raise typer.Exit(1)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("[red]需要浏览器组件[/]：uv sync --extra browser && uv run playwright install chromium")
        raise typer.Exit(1)

    out = session_path(platform)
    url = LOGIN_URLS[platform]
    console.print(f"[cyan]➜[/] 打开 {platform} 登录页，请用手机 App [bold]扫码登录[/]…")
    console.print(f"   登录成功后回到本窗口，按 [bold]回车[/] 保存会话（最长等待 {timeout}s）。")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="zh-CN",
                                      viewport={"width": 1280, "height": 900})
        page = context.new_page()
        try:
            page.goto(url, timeout=60000)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]⚠[/] 打开登录页出错（可继续手动导航）：{exc}")
        try:
            typer.prompt("登录完成后按回车", default="", show_default=False)
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(timeout * 1000)
        context.storage_state(path=str(out))
        browser.close()
    console.print(f"[green]✓[/] 已保存 {platform} 会话到 {out}（已在 .gitignore 中）。"
                  f"现在启用该平台的抓取源即可以登录态采集。")


@app.command("serve")
def serve_cmd() -> None:
    """Start the APScheduler loop (daily + weekly jobs)."""
    from chubb_ci.scheduler.jobs import run_scheduler

    run_scheduler(get_settings())


@app.command("dashboard")
def dashboard_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="开发模式自动重载"),
) -> None:
    """Run the dashboard web app (FastAPI + Uvicorn)."""
    import uvicorn

    console.print(f"[green]➜[/] 仪表盘: http://{host}:{port}")
    uvicorn.run("chubb_ci.web.app:app", host=host, port=port, reload=reload)


@app.command("load-real")
def load_real_cmd(
    crawl: bool = typer.Option(True, "--crawl/--no-crawl", help="是否实时抓取真实来源"),
) -> None:
    """Build an ALL-REAL dataset (deck + catalog + live crawl; no fabricated competitors)."""
    from chubb_ci.tools.load_real import load_real

    r = load_real(get_settings(), crawl=crawl)
    console.print(
        f"[green]✓[/] 已载入真实数据：{r['brands']} 个品牌档案、{r['own_products']} 款集宝产品、"
        f"{r['deck_products']} 款竞品(分析报告)、抓取入库 {r['crawled_products']} 款"
        f"（{r['crawled_ok']} 个来源）；合计 {r['total_products']} 款、{r['insights']} 条洞察。"
    )
    console.print("运行 [bold]chubb-ci dashboard[/] 查看仪表盘（真实数据）。")


@app.command("seed-demo")
def seed_demo_cmd(
    reset: bool = typer.Option(True, "--reset/--no-reset", help="载入前清空数据库"),
) -> None:
    """Populate the database with realistic demo data for the dashboard."""
    from chubb_ci.demo_seed import seed

    summary = seed(get_settings(), reset=reset)
    console.print(
        f"[green]✓[/] 已载入演示数据：{summary['competitors']} 家竞争对手、"
        f"{summary['products']} 款竞品、{summary['today_events']} 条今日变化、"
        f"{summary['hist_events']} 条历史变化；"
        f"{summary['brands']} 个品牌档案、{summary['own_products']} 款集宝产品、"
        f"{summary['pairs']} 组对标、{summary['insights']} 条市场洞察。"
    )
    console.print("运行 [bold]chubb-ci dashboard[/] 查看仪表盘。")


@app.command("sync-brands")
def sync_brands_cmd() -> None:
    """Sync config/brands.yaml + config/counterparts.yaml into the database."""
    from chubb_ci.storage.db import init_db, session_scope
    from chubb_ci.tools.brand_sync import sync_brands, sync_counterparts

    settings = get_settings()
    init_db(settings)
    root = settings.sources_path.parent  # config/ directory
    with session_scope(settings) as session:
        n_brands = sync_brands(session, root / "brands.yaml")
        n_pairs = sync_counterparts(session, root / "counterparts.yaml")
    console.print(f"[green]✓[/] 已同步 {n_brands} 个品牌档案、{n_pairs} 组对标配对")


@app.command("import-catalog")
def import_catalog_cmd(
    path: Path = typer.Argument("ChubbProductsList.xlsx", help="集宝产品目录 xlsx 路径"),
) -> None:
    """Import the 集宝 own-product catalog (replaces existing rows)."""
    from chubb_ci.analytics.refresh import refresh_insights
    from chubb_ci.storage.db import init_db, session_scope
    from chubb_ci.storage.repositories import Repository
    from chubb_ci.tools.catalog_import import import_catalog

    settings = get_settings()
    init_db(settings)
    with session_scope(settings) as session:
        n = import_catalog(session, path)
        insights = refresh_insights(Repository(session))
    console.print(f"[green]✓[/] 已导入 {n} 款集宝产品；重新计算得到 {len(insights)} 条市场洞察")


@app.command("ingest-email")
def ingest_email_cmd(
    limit: int = typer.Option(0, "--limit", help="最多处理最近 N 封（0=按配置）"),
) -> None:
    """Poll the 竞品订阅邮箱 (IMAP) → extract promos/products → 邮件订阅 channel."""
    from chubb_ci.crawler.email_ingest import run_email_ingest
    from chubb_ci.storage.db import init_db

    settings = get_settings()
    if not settings.email_user:
        console.print("[yellow]邮箱未配置。[/] 在 .env 设置 CHUBB_EMAIL_USER / "
                      "CHUBB_EMAIL_PASSWORD（163 授权码），可选 CHUBB_EMAIL_IMAP_HOST。")
        raise typer.Exit(1)
    init_db(settings)
    s = run_email_ingest(settings, limit=limit or None)
    console.print(
        f"[green]✓[/] 邮箱拉取 {s.fetched} 封：新处理 {s.processed}（入库 {s.products} 款）"
        f" · 去重跳过 {s.skipped_duplicates} · 出错 {len(s.errors)}"
    )
    for err in s.errors[:5]:
        console.print(f"[red]  ! {err}[/]")


@app.command("jd-prices")
def jd_prices_cmd(
    keyword: str = typer.Argument(..., help="搜索关键词，如「艾谱保险柜」"),
    limit: int = typer.Option(10, "--limit", help="返回条数"),
) -> None:
    """Query official JD Union prices by keyword (needs CHUBB_JD_UNION_APP_KEY/SECRET)."""
    from chubb_ci.crawler.jd_union import JDUnionClient

    settings = get_settings()
    client = JDUnionClient(settings)
    if not client.available:
        console.print("[yellow]JD Union 未配置。[/] 到 union.jd.com/openplatform 申请"
                      "（推广管理→导购媒体，个人可申请），将 appkey/secret 写入 .env 的 "
                      "CHUBB_JD_UNION_APP_KEY / CHUBB_JD_UNION_APP_SECRET。")
        raise typer.Exit(1)
    products = client.query_goods(keyword, page_size=limit)
    if not products:
        console.print("[yellow]无结果[/]（关键词无匹配，或接口权限/签名问题——见日志）")
        raise typer.Exit(0)
    table = Table(title=f"京东联盟 · {keyword}")
    table.add_column("商品", max_width=46)
    table.add_column("价格", justify="right")
    table.add_column("30天销量", justify="right")
    for p in products:
        table.add_row(p.product_name[:46],
                      f"¥{p.price:,.0f}" if p.price else "—",
                      str(p.sales_volume or "—"))
    console.print(table)


@app.command("ingest-pptx")
def ingest_pptx_cmd(
    path: Path = typer.Argument("CompetitorAnalysisV7.pptx", help="竞品分析 PPTX 路径"),
) -> None:
    """Import competitor product tables from the marketing deck (分析报告 channel)."""
    from chubb_ci.analytics.refresh import refresh_insights
    from chubb_ci.storage.db import init_db, session_scope
    from chubb_ci.storage.repositories import Repository
    from chubb_ci.tools.pptx_ingest import ingest_pptx

    settings = get_settings()
    init_db(settings)
    with session_scope(settings) as session:
        result = ingest_pptx(session, path)
        insights = refresh_insights(Repository(session))
    console.print(
        f"[green]✓[/] 已从 {path.name} 导入 {result['brands']} 个品牌的 "
        f"{result['products']} 款竞品；重新计算得到 {len(insights)} 条市场洞察"
    )


@app.command("ingest-pdf")
def ingest_pdf_cmd(
    path: Path = typer.Argument(..., help="ChubbSafes 介绍 PDF 路径"),
) -> None:
    """Extract PDF text into config/domain/chubbsafes_context.md (appends a raw section)."""
    from chubb_ci.tools.pdf_ingest import ingest_pdf

    settings = get_settings()
    out = ingest_pdf(path, settings.domain_context_path)
    console.print(f"[green]✓[/] 已更新领域背景: {out}")


agent_app = typer.Typer(help="研究智能体：ingest / research / enrich / sentiment")
app.add_typer(agent_app, name="agent")


def _run_agent(workflow: str, params: dict) -> None:
    from chubb_ci.schemas.models import AgentRun
    from chubb_ci.storage.db import init_db, session_scope
    from chubb_ci.agent.service import start_workflow

    settings = get_settings()
    init_db(settings)
    console.print(f"[cyan]➜[/] 启动智能体工作流 [bold]{workflow}[/]（前台运行，日志实时输出）")
    run_id = start_workflow(settings, workflow, params, background=False)
    with session_scope(settings) as session:
        run = session.get(AgentRun, run_id)
        status = "[green]✓ 完成[/]" if run.status == "done" else f"[red]✗ {run.status}[/]"
        console.print(
            f"{status} run #{run_id} · 迭代 {run.iterations} · tokens {run.tokens_in}/{run.tokens_out}"
            f" · 成本≈¥{run.cost_cny} · 声明 {run.facts_verified}通过/{run.facts_pending}待审"
        )
        if run.result_md:
            console.print("\n" + run.result_md)
        if run.error:
            console.print(f"[red]错误：{run.error}[/]")


@agent_app.command("ingest")
def agent_ingest_cmd(
    path: Path = typer.Argument("CompetitorAnalysisV7.pptx", help="PPTX/PDF 文档路径"),
) -> None:
    """文档摄取：竞品 PPT/手册 → 数据库（C1，含真实性核查）。"""
    _run_agent("ingest", {"path": str(path)})


@agent_app.command("research")
def agent_research_cmd(
    brand: str = typer.Argument(..., help="要深挖的品牌名"),
    url: str = typer.Option(None, "--url", help="直接指定要抓取的页面（无搜索服务时必填）"),
) -> None:
    """品牌深挖：检索/抓取 → 抽取 → 核查 → 入库（C2）。"""
    _run_agent("research", {"brand": brand, "url": url})


@agent_app.command("sentiment")
def agent_sentiment_cmd(
    goal: str = typer.Argument("集宝 ChubbSafes 保险柜", help="品牌或话题"),
) -> None:
    """舆情分析：联网检索相关内容 → 情感分类 → 生成舆情报告（需搜索服务）。"""
    _run_agent("sentiment", {"goal": goal})


@agent_app.command("enrich")
def agent_enrich_cmd(
    product_id: int = typer.Argument(..., help="要补充空缺参数的 ProductRecord ID"),
) -> None:
    """单品信息自动化搜集：浏览来源、交叉核查，只补空值。"""
    _run_agent("enrich", {"product_id": product_id})


@app.command("info")
def info_cmd() -> None:
    """Show effective configuration (secrets masked)."""
    settings = get_settings()
    from chubb_ci.llm.factory import resolve_model

    table = Table(title="ChubbAgent 配置")
    table.add_column("key")
    table.add_column("value")
    rows = {
        "llm_provider": settings.llm_provider,
        "llm_api_key": "***" if settings.llm_api_key else "(empty)",
        "extract_model": _safe(lambda: resolve_model(settings, "extract")),
        "weekly_model": _safe(lambda: resolve_model(settings, "weekly")),
        "database_url": settings.database_url,
        "sources_file": str(settings.sources_path),
        "daily_cron": settings.daily_cron,
        "weekly_cron": settings.weekly_cron,
        "timezone": settings.timezone,
    }
    for k, v in rows.items():
        table.add_row(k, str(v))
    console.print(table)


def _safe(fn) -> str:
    try:
        return str(fn())
    except Exception as exc:  # noqa: BLE001
        return f"(n/a: {exc})"


def main() -> None:
    app()


if __name__ == "__main__":
    main()
