"""FastAPI dashboard app: server-rendered pages + a few JSON/trigger endpoints.

Run:  uv run chubb-ci dashboard         (or)  uvicorn chubb_ci.web.app:app
"""

from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from chubb_ci.config.settings import get_settings
from chubb_ci.storage.db import init_db, session_scope
from chubb_ci.storage.repositories import Repository
from chubb_ci.web.services import DashboardService

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db(get_settings())
    yield


app = FastAPI(title="ChubbAgent Dashboard", version="0.1.0", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


def _service(session) -> DashboardService:
    return DashboardService(Repository(session), get_settings())


def _ctx(request: Request, active: str, **extra) -> dict:
    base = {"request": request, "active": active, "app_name": "ChubbAgent"}
    base.update(extra)
    return base


# =========================================================================
# Pages
# =========================================================================
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with session_scope(get_settings()) as session:
        svc = _service(session)
        ctx = _ctx(
            request, "dashboard",
            kpis=svc.kpis(),
            trend=svc.changes_trend(),
            severity=svc.severity_index(),
            feed=svc.recent_feed(),
            insights=svc.insight_summary(),
        )
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/reports", response_class=HTMLResponse)
def reports(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "reports", **_service(session).daily())
    return templates.TemplateResponse(request, "reports.html", ctx)


@app.get("/competitors", response_class=HTMLResponse)
def competitors(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "competitors", competitors=_service(session).competitors())
    return templates.TemplateResponse(request, "competitors.html", ctx)


@app.get("/competitors/{name}", response_class=HTMLResponse)
def competitor_profile(request: Request, name: str):
    with session_scope(get_settings()) as session:
        profile = _service(session).brand_profile(name)
        if profile is None:
            return templates.TemplateResponse(
                request, "competitors.html",
                _ctx(request, "competitors", competitors=_service(session).competitors()),
            )
        ctx = _ctx(request, "competitors", **profile)
    return templates.TemplateResponse(request, "competitor_profile.html", ctx)


@app.get("/benchmark", response_class=HTMLResponse)
def benchmark(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "benchmark", **_service(session).benchmark_lists())
    return templates.TemplateResponse(request, "benchmark.html", ctx)


@app.get("/api/benchmark/compare")
def benchmark_compare(own_id: int, comp_id: int) -> JSONResponse:
    with session_scope(get_settings()) as session:
        detail = _service(session).compare_detail(own_id, comp_id)
    if detail is None:
        return JSONResponse({"error": "未找到所选产品"}, status_code=404)
    return JSONResponse(detail)


@app.post("/api/own-products")
async def create_own_product(request: Request) -> JSONResponse:
    """Manually add a 集宝 (own) product for benchmarking."""
    from chubb_ci.diff.matching import normalize_product_key
    from chubb_ci.normalize import fire_hours, security_score, volume_l
    from chubb_ci.schemas.models import OwnProduct

    body = await request.json()
    name = (body.get("product_name") or "").strip()
    if not name:
        return JSONResponse({"error": "product_name 必填"}, status_code=400)

    def num(key, cast=float):
        v = body.get(key)
        if v in (None, ""):
            return None
        try:
            return cast(str(v).replace("¥", "").replace(",", "").strip())
        except ValueError:
            return None

    rec = OwnProduct(
        product_name=name, product_key=normalize_product_key(name),
        series=(body.get("series") or "").strip() or None,
        category=(body.get("category") or "保险柜").strip(),
        price=num("price"), width_mm=num("width_mm"), depth_mm=num("depth_mm"),
        height_mm=num("height_mm"), capacity_l=num("capacity_l"), weight_kg=num("weight_kg"),
        fire_rating=(body.get("fire_rating") or "").strip() or None,
        gb_grade=(body.get("gb_grade") or "").strip() or None,
        lock_type=(body.get("lock_type") or "").strip() or None,
        lead_time_days=int(num("lead_time_days", float) or 0),
    )
    rec.capacity_l = rec.capacity_l or volume_l(rec.width_mm, rec.depth_mm, rec.height_mm)
    rec.fire_hours = fire_hours(rec.fire_rating)
    rec.security_score = security_score(rec.gb_grade, rec.euro_grade)
    with session_scope(get_settings()) as session:
        session.add(rec)
        session.flush()
        pid = rec.id
    return JSONResponse({"status": "ok", "id": pid})


@app.delete("/api/own-products/{pid}")
def delete_own_product(pid: int) -> JSONResponse:
    from chubb_ci.schemas.models import OwnProduct

    with session_scope(get_settings()) as session:
        rec = session.get(OwnProduct, pid)
        if rec is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        session.delete(rec)
    return JSONResponse({"status": "ok"})


@app.get("/market", response_class=HTMLResponse)
def market(request: Request):
    """市场情况 — merged 市场地图 + 价格变动 + 市场趋势 (tabbed sections)."""
    with session_scope(get_settings()) as session:
        svc = _service(session)
        ctx = _ctx(request, "market", map=svc.market_map(),
                   leaderboard=svc.value_leaderboard(),
                   pc=svc.price_changes(),
                   trends=svc.market_trends())
    return templates.TemplateResponse(request, "market.html", ctx)


# Old bookmarks → the merged page.
@app.get("/market-map")
@app.get("/price-changes")
@app.get("/market-trends")
def _market_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/market", status_code=301)


@app.get("/price-comparison", response_class=HTMLResponse)
def price_comparison(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "pricecmp", **_service(session).price_comparison())
    return templates.TemplateResponse(request, "price_comparison.html", ctx)


@app.get("/products", response_class=HTMLResponse)
def products(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "products", **_service(session).products())
    return templates.TemplateResponse(request, "products.html", ctx)


@app.get("/products/{pid}", response_class=HTMLResponse)
def product_detail(request: Request, pid: int):
    with session_scope(get_settings()) as session:
        detail = _service(session).product_detail(pid)
        if detail is None:
            ctx = _ctx(request, "products", **_service(session).products())
            return templates.TemplateResponse(request, "products.html", ctx)
        ctx = _ctx(request, "products", **detail)
    return templates.TemplateResponse(request, "product_detail.html", ctx)


@app.get("/ingest", response_class=HTMLResponse)
def ingest_page(request: Request):
    """手动录入 — paste text → LLM identifies the product → editable form → save."""
    return templates.TemplateResponse(request, "ingest.html", _ctx(request, "products"))


# Per-feature metadata drives the hub cards + each dedicated sub-page (title, icon,
# whether it needs the web-search key, and step-by-step usage instructions).
_AGENT_FEATURES: dict[str, dict] = {
    "research": {
        "key": "research", "title": "品牌深挖", "icon": "travel_explore",
        "subtitle": "给定一个品牌，智能体联网检索、抓取并核查，把可信信息写入数据库。",
        "needs_search": True,
        "how": [
            "输入要研究的竞品品牌名（如「盾牌 Dunpai」）。",
            "可选：直接指定一个页面 URL —— 未配置搜索时必填，配置后作为优先来源。",
            "智能体按 检索→抓取→抽取→真实性核查→评估 的闭环运行，全程有界（预算/轮次/时间上限）。",
            "已核实的产品与字段自动入库；存疑信息进入下方「信息确认队列」等你 采纳/驳回。",
        ],
        "note": "只有多来源互证/通过一致性校验的字段才自动写库，其余一律人工确认，绝不盲信。",
    },
    "enrich": {
        "key": "enrich", "title": "竞品信息自动化搜集", "icon": "manage_search",
        "subtitle": "给定一个产品，智能体浏览它已保存的链接并联网佐证，只补齐当前空缺的参数。",
        "needs_search": True,
        "how": [
            "在「产品情报」找到目标产品，复制其 ID 填入下方（或从产品详情页点「自动搜集参数」直接触发）。",
            "智能体只浏览该产品已保存的 商品链接/来源链接，并按型号联网检索佐证。",
            "仅填补当前为空的字段（尺寸/重量/容积/认证等），已有数据绝不被覆盖。",
            "多源一致的值自动写入；低置信度值进入人工确认队列。",
        ],
        "note": "适合把苏宁/官网抓到、但规格不全的产品补全参数，供对标与比价使用。",
    },
    "ingest": {
        "key": "ingest", "title": "文档摄取", "icon": "upload_file",
        "subtitle": "上传竞品分析 PPT 或产品手册 PDF，自动抽取其中的产品表与品牌档案。",
        "needs_search": False,
        "how": [
            "上传一个 .pptx 或 .pdf 文件（如市场部的竞品分析报告）。",
            "文档中的产品价格/销量/认证表格被确定性解析并入库（分析报告渠道）。",
            "LLM 从文中抽取的品牌定位/供应链等档案声明会进入人工确认队列。",
            "也可直接选择项目根目录下已有的文档。",
        ],
        "note": "结构化表格走确定性解析（不经 LLM），只有主观档案声明才需人工确认。",
    },
    "sentiment": {
        "key": "sentiment", "title": "舆情分析", "icon": "reviews",
        "subtitle": "联网检索关于 ChubbSafes/集宝（或任意话题）的内容，分类情感并生成舆情报告。",
        "needs_search": True,
        "how": [
            "输入要分析的品牌或话题（默认「集宝 ChubbSafes 保险柜」）。",
            "智能体从口碑/评价/新闻/投诉多个角度联网检索。",
            "对每条结果逐一判定 正面/中性/负面，并按来源确定性统计分布。",
            "生成带来源引用的中文舆情分析报告（概览/正面/风险/竞品对比/建议）。",
        ],
        "note": "所有结论均标注来源序号；情感分布数字来自逐条来源的分类统计，可追溯。",
    },
}


@app.get("/research-agent", response_class=HTMLResponse)
def research_agent(request: Request):
    """Agent hub: feature cards + recent runs (each feature has its own sub-page)."""
    search_on = build_search_available()
    ctx = _ctx(request, "agent", features=list(_AGENT_FEATURES.values()),
               search_on=search_on)
    return templates.TemplateResponse(request, "research_agent.html", ctx)


@app.get("/research-agent/{feature}", response_class=HTMLResponse)
def research_agent_feature(request: Request, feature: str):
    meta = _AGENT_FEATURES.get(feature)
    if meta is None:
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/research-agent", status_code=302)
    ctx = _ctx(request, "agent", feature=meta, search_on=build_search_available())
    return templates.TemplateResponse(request, "agent_feature.html", ctx)


def build_search_available() -> bool:
    from chubb_ci.agent.search import build_search

    return getattr(build_search(get_settings()), "available", False)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "settings", status=_service(session).system_status())
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.get("/api/status/llm")
def llm_status() -> JSONResponse:
    """Live connectivity probe: does the configured LLM key actually work?"""
    from chubb_ci.llm.base import LLMError
    from chubb_ci.llm.factory import build_llm, resolve_model

    settings = get_settings()
    if not settings.llm_api_key:
        return JSONResponse({"ok": False, "message": "未配置 API Key（CHUBB_LLM_API_KEY）"})
    try:
        llm = build_llm(settings)
        resp = llm.complete(system="reply one word", user="say OK",
                            model=resolve_model(settings, "daily"))
        return JSONResponse({"ok": True, "message": f"连接正常（{resp.model}）",
                             "reply": resp.content.strip()[:20]})
    except LLMError as exc:
        return JSONResponse({"ok": False, "message": f"连接失败：{str(exc)[:160]}"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "message": f"错误：{str(exc)[:160]}"})


# =========================================================================
# JSON / actions
# =========================================================================
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/dashboard-data")
def dashboard_data() -> JSONResponse:
    with session_scope(get_settings()) as session:
        svc = _service(session)
        return JSONResponse({
            "kpis": svc.kpis(),
            "trend": svc.changes_trend(),
            "severity": svc.severity_index(),
        })


@app.post("/api/brands/{name}/focus")
def toggle_focus(name: str) -> JSONResponse:
    """Toggle the 重点关注 (key-competitor) label on a brand."""
    with session_scope(get_settings()) as session:
        is_focus = _service(session).toggle_focus(name)
    return JSONResponse({"name": name, "is_focus": is_focus})


@app.get("/api/search")
def search(q: str = "") -> JSONResponse:
    """Global search over products, competitors, and brand profiles."""
    q = q.strip().lower()
    if len(q) < 1:
        return JSONResponse({"results": []})
    results: list[dict] = []
    with session_scope(get_settings()) as session:
        svc = _service(session)
        seen_companies: set[str] = set()
        for row in svc.products()["rows"]:
            company = row["company"] or ""
            if q in row["product_name"].lower() or q in company.lower():
                if company and q in company.lower() and company not in seen_companies:
                    seen_companies.add(company)
                    results.append({"type": "竞争对手", "label": company,
                                    "href": f"/competitors/{company}"})
                if q in row["product_name"].lower():
                    results.append({
                        "type": "产品", "label": f"{row['product_name']}（{company}）",
                        "href": f"/products?q={row['product_name']}",
                    })
        for b in svc.repo.all_brands():
            if q in b.name.lower() and b.name not in seen_companies:
                results.append({"type": "品牌档案", "label": b.name,
                                "href": f"/competitors/{b.name}"})
    return JSONResponse({"results": results[:10]})


@app.get("/api/notifications")
def notifications() -> JSONResponse:
    """Recent change events + insights for the top-bar bell dropdown."""
    with session_scope(get_settings()) as session:
        svc = _service(session)
        feed = svc.recent_feed(5)
        insights = svc.insight_summary()
    items = [{"kind": "event", "title": f"{i['company']} · {i['title']}",
              "detail": i["summary"], "time": i["time_ago"]} for i in feed]
    items += [{"kind": "insight", "title": f"[{i['type_label']}] {i['title']}",
               "detail": i["detail"], "time": ""} for i in insights["items"][:3]]
    return JSONResponse({"items": items[:8], "unread": len(feed)})


_IMG_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/gif": ".gif", "image/avif": ".avif"}
_MAX_IMG_BYTES = 5_000_000


def _img_url_safe(url: str) -> bool:
    """SSRF guard: only http(s), and never internal/loopback/private hosts."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    try:
        if ipaddress.ip_address(host).is_private:
            return False
    except ValueError:
        pass  # a domain name (marketplace CDN) — allowed
    return True


@app.get("/api/img")
def image_proxy(url: str) -> Response:
    """Fetch + cache a product image (dodges marketplace hotlink/referer 403s)."""
    if not _img_url_safe(url):
        return Response(status_code=400)
    settings = get_settings()
    cache_dir = settings.data_path / "img_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]

    for existing in cache_dir.glob(f"{digest}.*"):
        return FileResponse(existing, headers={"Cache-Control": "public, max-age=604800"})

    import httpx

    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={
                "User-Agent": settings.user_agent, "Referer": referer,
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            })
            resp.raise_for_status()
    except Exception:  # noqa: BLE001 - broken image → 404, template shows fallback icon
        return Response(status_code=404)

    ctype = resp.headers.get("content-type", "").split(";")[0].strip()
    if ctype not in _IMG_EXT or len(resp.content) > _MAX_IMG_BYTES:
        return Response(status_code=415)
    path = cache_dir / f"{digest}{_IMG_EXT[ctype]}"
    path.write_bytes(resp.content)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/export/products.csv")
def export_products_csv() -> StreamingResponse:
    with session_scope(get_settings()) as session:
        rows = _service(session).products()["rows"]
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Excel opens Chinese correctly
    cols = ["company", "product_name", "category", "price", "prev_price", "diff_pct",
            "promotion", "gb_grade", "capacity_l", "weight_kg", "fire_hours",
            "security_score", "price_per_l", "price_per_kg", "lead_time_days",
            "sales_volume", "status_label", "product_url", "image_url", "last_updated"]
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chubb_products.csv"},
    )


# =========================================================================
# Product editing (产品情报 is mutable) + 手动录入 ingest
# =========================================================================
_PRODUCT_STR_FIELDS = ("product_name", "company", "category", "series", "channel",
                       "promotion", "gb_grade", "euro_grade", "fire_rating", "lock_type",
                       "availability", "status_label", "image_url", "product_url")
_PRODUCT_NUM_FIELDS = ("price", "capacity_l", "weight_kg", "width_mm", "depth_mm",
                       "height_mm", "fire_hours", "security_score", "lead_time_days",
                       "sales_volume")


def _apply_product_fields(rec, body: dict) -> None:
    """Apply whitelisted fields to a ProductRecord + recompute derived metrics."""
    from chubb_ci.diff.matching import model_code, normalize_product_key
    from chubb_ci.normalize import fire_hours, security_score, volume_l

    for f in _PRODUCT_STR_FIELDS:
        if f in body:
            v = (str(body[f]).strip() or None) if body[f] is not None else None
            setattr(rec, f, v if f != "product_name" else (v or rec.product_name))
    for f in _PRODUCT_NUM_FIELDS:
        if f in body:
            v = body[f]
            if v in (None, ""):
                setattr(rec, f, None)
            else:
                try:
                    num = float(str(v).replace("¥", "").replace(",", ""))
                except ValueError:
                    continue
                setattr(rec, f, int(num) if f in ("security_score", "lead_time_days",
                                                  "sales_volume") else num)
    # keys + derived metrics follow the edited values (same rules as crawl ingest)
    rec.product_key = normalize_product_key(rec.product_name)
    rec.model_code = model_code(rec.product_name)
    if "capacity_l" not in body:
        rec.capacity_l = rec.capacity_l or volume_l(rec.width_mm, rec.depth_mm, rec.height_mm)
    if "fire_hours" not in body and rec.fire_rating:
        rec.fire_hours = rec.fire_hours or fire_hours(rec.fire_rating)
    if "security_score" not in body and (rec.gb_grade or rec.euro_grade):
        rec.security_score = rec.security_score or security_score(rec.gb_grade, rec.euro_grade)


@app.post("/api/products")
async def create_product(request: Request) -> JSONResponse:
    """手动录入: create a product record (channel 手动录入, no snapshot)."""
    from chubb_ci.schemas.models import ProductRecord

    body = await request.json()
    if not (body.get("product_name") or "").strip():
        return JSONResponse({"error": "product_name 必填"}, status_code=400)
    rec = ProductRecord(source_name="manual", channel="手动录入",
                        company=(body.get("company") or "").strip() or "未知品牌",
                        product_name=body["product_name"].strip(), category="保险柜")
    _apply_product_fields(rec, body)
    with session_scope(get_settings()) as session:
        session.add(rec)
        session.flush()
        pid = rec.id
    return JSONResponse({"status": "ok", "id": pid})


@app.patch("/api/products/{pid}")
async def update_product(pid: int, request: Request) -> JSONResponse:
    from chubb_ci.schemas.models import ProductRecord

    body = await request.json()
    with session_scope(get_settings()) as session:
        rec = session.get(ProductRecord, pid)
        if rec is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        _apply_product_fields(rec, body)
        session.add(rec)
    return JSONResponse({"status": "ok", "id": pid})


@app.delete("/api/products/{pid}")
def delete_product(pid: int) -> JSONResponse:
    """Delete a product — removes ALL history rows for (company, product_key), else an
    older snapshot of the same product would immediately resurface in the list."""
    from sqlmodel import select

    from chubb_ci.schemas.models import ProductRecord

    with session_scope(get_settings()) as session:
        rec = session.get(ProductRecord, pid)
        if rec is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        rows = session.exec(select(ProductRecord).where(
            ProductRecord.company == rec.company,
            ProductRecord.product_key == rec.product_key)).all()
        for r in rows:
            session.delete(r)
    return JSONResponse({"status": "ok", "deleted": len(rows)})


@app.post("/api/ingest/parse")
async def ingest_parse(request: Request) -> JSONResponse:
    """Paste text → LLM identifies structured product fields (nothing is saved yet)."""
    from chubb_ci.config.sources import PageType, Source
    from chubb_ci.extractor.extractor import extract_products
    from chubb_ci.llm.factory import build_llm, resolve_model

    body = await request.json()
    text = (body.get("text") or "").strip()
    if len(text) < 10:
        return JSONResponse({"error": "请粘贴至少 10 个字符的产品描述"}, status_code=400)
    settings = get_settings()
    source = Source(name="manual-ingest", company=(body.get("company") or "").strip() or "未知品牌",
                    urls=["manual://paste"], page_type=PageType.PRODUCT, channel="手动录入")
    try:
        result = extract_products(
            build_llm(settings), model=resolve_model(settings, "extract"), source=source,
            url="manual://paste", page_text=text[: settings.max_extract_chars],
            domain_context=settings.load_domain_context(),
            temperature=settings.llm_temperature)
    except Exception as exc:  # noqa: BLE001 - surface LLM/config errors to the UI
        return JSONResponse({"error": str(exc)}, status_code=502)
    if not result.ok:
        return JSONResponse({"error": result.error or "识别失败"}, status_code=502)
    return JSONResponse({"products": [p.model_dump() for p in result.products]})


_UPLOAD_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                 "image/gif": ".gif"}
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@app.post("/api/upload")
async def upload_image(request: Request) -> JSONResponse:
    """Save a pasted/selected product image (base64 data-URL) → /uploads/<sha>.<ext>."""
    import base64

    body = await request.json()
    data = body.get("data") or ""
    mime = "image/jpeg"
    if data.startswith("data:"):
        head, _, data = data.partition(",")
        mime = head.split(":", 1)[1].split(";", 1)[0].strip().lower()
    if mime not in _UPLOAD_TYPES:
        return JSONResponse({"error": f"不支持的图片类型: {mime}"}, status_code=415)
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "无效的图片数据"}, status_code=400)
    if not raw or len(raw) > _MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "图片为空或超过 5MB"}, status_code=413)
    settings = get_settings()
    updir = settings.data_path / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    fname = hashlib.sha256(raw).hexdigest()[:16] + _UPLOAD_TYPES[mime]
    (updir / fname).write_bytes(raw)
    return JSONResponse({"url": f"/uploads/{fname}"})


@app.get("/uploads/{fname}")
def serve_upload(fname: str):
    """Serve manually-uploaded product images (single flat dir, no traversal)."""
    settings = get_settings()
    path = settings.data_path / "uploads" / Path(fname).name
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})


# =========================================================================
# Agent (Phase C)
# =========================================================================
def _safe_ingest_path(raw: str | None) -> tuple[bool, str]:
    """Restrict ingest to .pptx/.pdf inside the repo root or the uploads dir.

    The path comes from the client, so it must be confined — never ingest an arbitrary
    server file. Accepts a bare filename (resolved against those dirs) or a full path
    that lands inside them.
    """
    if not raw:
        return False, ""
    root = Path(__file__).resolve().parents[2]
    updir = (get_settings().data_path / "uploads").resolve()
    allowed = [root.resolve(), updir]
    candidate = Path(raw)
    tries = [candidate] if candidate.is_absolute() else [root / raw, updir / raw]
    for p in tries:
        try:
            rp = p.resolve()
        except (OSError, RuntimeError):
            continue
        if (rp.suffix.lower() in (".pptx", ".pdf") and rp.is_file()
                and any(rp == base or base in rp.parents for base in allowed)):
            return True, str(rp)
    return False, ""


@app.post("/api/agent/start")
async def agent_start(request: Request) -> JSONResponse:
    """Start an agent workflow in the background; returns the run id."""
    from chubb_ci.agent.service import WORKFLOWS, start_workflow

    body = await request.json()
    workflow = (body.get("workflow") or "").strip()
    if workflow not in WORKFLOWS:
        return JSONResponse({"error": f"workflow must be one of {WORKFLOWS}"}, status_code=400)
    params = {k: v for k, v in body.items()
              if k in ("brand", "url", "goal", "path", "product_id") and v is not None and v != ""}
    if workflow == "research" and not params.get("brand"):
        return JSONResponse({"error": "research 需要 brand"}, status_code=400)
    if workflow == "ingest":
        ok, resolved = _safe_ingest_path(params.get("path"))
        if not ok:
            return JSONResponse({"error": "ingest 需要有效的 pptx/pdf 文件"}, status_code=400)
        params["path"] = resolved
    if workflow == "enrich":
        try:
            params["product_id"] = int(params["product_id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "enrich 需要有效的 product_id"}, status_code=400)
    run_id = start_workflow(get_settings(), workflow, params, background=True)
    return JSONResponse({"run_id": run_id})


@app.get("/api/agent/runs")
def agent_runs() -> JSONResponse:
    from sqlmodel import select

    from chubb_ci.schemas.models import AgentRun

    with session_scope(get_settings()) as session:
        stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(10)  # type: ignore[union-attr]
        runs = session.exec(stmt).all()
        return JSONResponse({"runs": [
            {"id": r.id, "workflow": r.workflow, "goal": r.goal, "status": r.status,
             "started_at": r.started_at.isoformat() if r.started_at else None,
             "iterations": r.iterations, "cost_cny": r.cost_cny,
             "facts_pending": r.facts_pending}
            for r in runs
        ]})


@app.get("/api/agent/runs/{run_id}")
def agent_run_detail(run_id: int) -> JSONResponse:
    from sqlmodel import select

    from chubb_ci.schemas.models import AgentRun, AgentStepRecord, PendingFact

    with session_scope(get_settings()) as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        steps = session.exec(
            select(AgentStepRecord).where(AgentStepRecord.run_id == run_id)
            .order_by(AgentStepRecord.ts)).all()  # type: ignore[arg-type]
        facts = session.exec(
            select(PendingFact).where(PendingFact.run_id == run_id)).all()
        return JSONResponse({
            "run": {"id": run.id, "workflow": run.workflow, "goal": run.goal,
                    "status": run.status, "iterations": run.iterations,
                    "tokens_in": run.tokens_in, "tokens_out": run.tokens_out,
                    "cost_cny": run.cost_cny, "result_md": run.result_md,
                    "error": run.error},
            "steps": [{"ts": s.ts.strftime("%H:%M:%S"), "node": s.node,
                       "message": s.message, "detail": s.detail} for s in steps],
            "facts": [{"id": f.id, "claim": f.claim, "subject": f.subject,
                       "field": f.field, "value": f.value, "sources": f.sources,
                       "confidence": f.confidence, "status": f.status,
                       "review_note": f.review_note} for f in facts],
        })


@app.get("/api/agent/runs/{run_id}/stream")
async def agent_run_stream(run_id: int) -> StreamingResponse:
    """SSE stream of a run's live log: `step`, `status`, and final `done` events.

    Backed by incremental DB reads (0.5s cadence server-side), so it works for runs
    started from the dashboard *and* from the CLI in another process, over a single
    long-lived connection. Ends automatically when the run leaves `running`.
    """
    import asyncio
    import json as _json

    from sqlmodel import select

    from chubb_ci.schemas.models import AgentRun, AgentStepRecord

    def _read(last_step_id: int):
        with session_scope(get_settings()) as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                return None, [], last_step_id
            stmt = (select(AgentStepRecord)
                    .where(AgentStepRecord.run_id == run_id,
                           AgentStepRecord.id > last_step_id)
                    .order_by(AgentStepRecord.id))  # type: ignore[arg-type]
            steps = session.exec(stmt).all()
            if steps:
                last_step_id = steps[-1].id
            payload = {
                "status": run.status, "iterations": run.iterations,
                "tokens_in": run.tokens_in, "tokens_out": run.tokens_out,
                "cost_cny": run.cost_cny, "error": run.error,
            }
            return payload, steps, last_step_id

    async def event_stream():
        last_step_id = 0
        last_status: dict | None = None
        # ~10 min hard cap on a single stream (matches the agent time budget).
        for _ in range(1200):
            status, steps, last_step_id = await asyncio.to_thread(_read, last_step_id)
            if status is None:
                yield f"event: error\ndata: {_json.dumps({'error': 'run not found'})}\n\n"
                return
            for s in steps:
                data = {"ts": s.ts.strftime("%H:%M:%S"), "node": s.node,
                        "message": s.message, "detail": s.detail}
                yield f"event: step\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
            if status != last_status:
                last_status = status
                yield f"event: status\ndata: {_json.dumps(status, ensure_ascii=False)}\n\n"
            if status["status"] != "running":
                yield f"event: done\ndata: {_json.dumps(status, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.5)
        yield "event: done\ndata: {\"status\": \"timeout\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/agent/facts/{fact_id}/review")
async def agent_fact_review(fact_id: int, request: Request) -> JSONResponse:
    from chubb_ci.agent.service import review_fact

    body = await request.json()
    with session_scope(get_settings()) as session:
        result = review_fact(session, fact_id,
                             accept=bool(body.get("accept")),
                             note=body.get("note", ""))
    status = 400 if "error" in result else 200
    return JSONResponse(result, status_code=status)


@app.get("/api/agent/files")
def agent_files() -> JSONResponse:
    """Ingestable documents (pptx/pdf) in the project root + uploads dir."""
    root = Path(__file__).resolve().parents[2]
    names = {p.name: str(p) for p in root.iterdir()
             if p.suffix.lower() in (".pptx", ".pdf") and p.is_file()}
    updir = get_settings().data_path / "uploads"
    if updir.is_dir():
        for p in updir.iterdir():
            if p.suffix.lower() in (".pptx", ".pdf") and p.is_file():
                names[p.name] = str(p)
    return JSONResponse({"files": sorted(names), "paths": names})


_DOC_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/pdf": ".pdf",
}
_MAX_DOC_BYTES = 40 * 1024 * 1024


@app.post("/api/agent/upload")
async def agent_upload(request: Request) -> JSONResponse:
    """Upload a PPTX/PDF (base64 data-URL) → data/uploads → returns its server path."""
    import base64

    body = await request.json()
    data = body.get("data") or ""
    name = (body.get("filename") or "doc").strip()
    mime = ""
    if data.startswith("data:"):
        head, _, data = data.partition(",")
        mime = head.split(":", 1)[1].split(";", 1)[0].strip().lower()
    ext = _DOC_TYPES.get(mime) or Path(name).suffix.lower()
    if ext not in (".pptx", ".pdf"):
        return JSONResponse({"error": "仅支持 .pptx 或 .pdf 文件"}, status_code=415)
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "无效的文件数据"}, status_code=400)
    if not raw or len(raw) > _MAX_DOC_BYTES:
        return JSONResponse({"error": "文件为空或超过 40MB"}, status_code=413)
    updir = get_settings().data_path / "uploads"
    updir.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(c for c in Path(name).stem if c.isalnum() or c in "-_")[:40] or "doc"
    fname = f"{safe_stem}-{hashlib.sha256(raw).hexdigest()[:8]}{ext}"
    path = updir / fname
    path.write_bytes(raw)
    return JSONResponse({"path": str(path), "filename": fname})


@app.post("/api/trigger/{kind}")
def trigger(kind: str) -> JSONResponse:
    """Run a daily/weekly pipeline synchronously and return counts."""
    from chubb_ci.pipeline import run_daily, run_weekly

    settings = get_settings()
    if kind == "daily":
        draft = run_daily(settings)
    elif kind == "weekly":
        draft = run_weekly(settings)
    else:
        return JSONResponse({"error": "kind must be daily or weekly"}, status_code=400)
    return JSONResponse({"status": "ok", "kind": kind, "events": draft.num_events})
