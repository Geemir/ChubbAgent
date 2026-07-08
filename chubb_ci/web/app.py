"""FastAPI dashboard app: server-rendered pages + a few JSON/trigger endpoints.

Run:  uv run chubb-ci dashboard         (or)  uvicorn chubb_ci.web.app:app
"""

from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
        ctx = _ctx(request, "benchmark", **_service(session).benchmark())
    return templates.TemplateResponse(request, "benchmark.html", ctx)


@app.get("/market-map", response_class=HTMLResponse)
def market_map(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "marketmap", map=_service(session).market_map())
    return templates.TemplateResponse(request, "market_map.html", ctx)


@app.get("/products", response_class=HTMLResponse)
def products(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "products", **_service(session).products())
    return templates.TemplateResponse(request, "products.html", ctx)


@app.get("/promotions", response_class=HTMLResponse)
def promotions(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "promotions", **_service(session).promotions())
    return templates.TemplateResponse(request, "promotions.html", ctx)


@app.get("/price-changes", response_class=HTMLResponse)
def price_changes(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "price", **_service(session).price_changes())
    return templates.TemplateResponse(request, "price_changes.html", ctx)


@app.get("/market-trends", response_class=HTMLResponse)
def market_trends(request: Request):
    with session_scope(get_settings()) as session:
        ctx = _ctx(request, "trends", trends=_service(session).market_trends())
    return templates.TemplateResponse(request, "market_trends.html", ctx)


@app.get("/research-agent", response_class=HTMLResponse)
def research_agent(request: Request):
    return templates.TemplateResponse(request, "research_agent.html", _ctx(request, "agent"))


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


@app.get("/api/export/products.csv")
def export_products_csv() -> StreamingResponse:
    with session_scope(get_settings()) as session:
        rows = _service(session).products()["rows"]
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Excel opens Chinese correctly
    cols = ["company", "product_name", "category", "price", "prev_price", "diff_pct",
            "promotion", "gb_grade", "capacity_l", "weight_kg", "fire_hours",
            "security_score", "price_per_l", "price_per_kg", "lead_time_days",
            "status_label", "last_updated"]
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
# Agent (Phase C)
# =========================================================================
@app.post("/api/agent/start")
async def agent_start(request: Request) -> JSONResponse:
    """Start an agent workflow in the background; returns the run id."""
    from chubb_ci.agent.service import WORKFLOWS, start_workflow

    body = await request.json()
    workflow = (body.get("workflow") or "").strip()
    if workflow not in WORKFLOWS:
        return JSONResponse({"error": f"workflow must be one of {WORKFLOWS}"}, status_code=400)
    params = {k: v for k, v in body.items() if k in ("brand", "url", "goal", "path") and v}
    if workflow == "research" and not params.get("brand"):
        return JSONResponse({"error": "research 需要 brand"}, status_code=400)
    if workflow == "ingest" and not params.get("path"):
        return JSONResponse({"error": "ingest 需要 path"}, status_code=400)
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
    """Ingestable documents (pptx/pdf) in the project root."""
    root = Path(__file__).resolve().parents[2]
    files = sorted(
        p.name for p in root.iterdir()
        if p.suffix.lower() in (".pptx", ".pdf") and p.is_file()
    )
    return JSONResponse({"files": files})


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
