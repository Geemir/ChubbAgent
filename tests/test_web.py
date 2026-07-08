"""Tests for the dashboard service and FastAPI routes (seeded temp DB)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import chubb_ci.web.app as webapp  # noqa: E402
from chubb_ci.demo_seed import seed  # noqa: E402
from chubb_ci.storage.db import session_scope  # noqa: E402
from chubb_ci.storage.repositories import Repository  # noqa: E402
from chubb_ci.web.services import DashboardService, event_severity  # noqa: E402
from chubb_ci.schemas.models import DiffEvent, EventType  # noqa: E402


def test_event_severity_thresholds():
    def ev(pct):
        return DiffEvent(event_type=EventType.PRICE_CHANGE.value, pct_change=pct)

    assert event_severity(ev(-20)) == "Crit"
    assert event_severity(ev(-10)) == "High"
    assert event_severity(ev(-4)) == "Med"
    assert event_severity(ev(-1)) == "Low"
    assert event_severity(DiffEvent(event_type=EventType.DISCONTINUED.value)) == "High"


def test_dashboard_service_view_models(settings):
    seed(settings, reset=True)
    with session_scope(settings) as session:
        svc = DashboardService(Repository(session), settings)

        kpis = svc.kpis()
        assert kpis["competitors_monitored"] >= 6
        assert kpis["products_tracked"] > 0
        assert kpis["changes_today"] >= 1

        trend = svc.changes_trend(days=14)
        assert len(trend["labels"]) == 14
        assert sum(trend["values"]) >= 1

        sev = svc.severity_index()
        assert set(sev["labels"]) == {"Low", "Med", "High", "Crit"}

        assert svc.recent_feed(5)
        assert len(svc.competitors()) >= 6

        products = svc.products()
        assert products["rows"]
        assert products["categories"]
        # at least one product shows a computed price diff
        assert any(r["diff_pct"] is not None for r in products["rows"])

        daily = svc.daily()
        assert daily["price_moves"]
        assert daily["report_md"]

        promos = svc.promotions()
        assert promos["items"]  # seed has active promotions

        pc = svc.price_changes()
        assert pc["rows"] and pc["stats"]["total"] == len(pc["rows"])
        assert pc["stats"]["downs"] >= 1

        trends = svc.market_trends()
        assert len(trends["price_direction"]["labels"]) == 30
        assert trends["categories"]["values"]
        assert trends["competitor_activity"]["labels"]

        # --- business-framework views (Phase A/B) ---
        bench = svc.benchmark()
        assert bench["own_count"] > 40           # real ChubbProductsList.xlsx imported
        assert bench["pair_count"] >= 1          # counterparts.yaml pairs resolved
        row = bench["rows"][0]
        assert row["price_diff_pct"] is not None

        mm = svc.market_map()
        assert mm["own_points"]                  # 集宝 points on the scatter
        assert mm["scatter"]                     # competitor series
        assert len(mm["bands"]) == 5             # capacity brackets
        assert any(q["own"] for q in mm["quad"])

        ins = svc.insight_summary()
        assert ins["total"] >= 1
        assert ins["counts"]["logistics_advantage"] >= 1  # lead 0 vs seeded 3-15d

        profile = svc.brand_profile("永发 Yongfa")
        assert profile is not None
        assert profile["brand"] is not None      # §6 profile synced from brands.yaml
        assert profile["brand"].positioning
        assert profile["num_products"] >= 4

        # extended product columns
        prow = svc.products()["rows"][0]
        for col in ("capacity_l", "fire_hours", "security_score", "price_per_l",
                    "lead_time_days"):
            assert col in prow


@pytest.fixture
def client(settings, monkeypatch):
    seed(settings, reset=True)
    monkeypatch.setattr(webapp, "get_settings", lambda: settings)
    with TestClient(webapp.app) as c:
        yield c


def test_pages_return_200(client):
    for path in ["/", "/reports", "/competitors", "/products",
                 "/benchmark", "/market-map", "/competitors/永发 Yongfa",
                 "/promotions", "/price-changes", "/market-trends", "/research-agent",
                 "/health"]:
        resp = client.get(path)
        assert resp.status_code == 200, path


def test_focus_toggle_and_competitor_merge(client):
    # Profiled-but-uncrawled brands (e.g. Agresti) appear in the directory.
    comp = client.get("/competitors").text
    assert "Agresti" in comp
    assert "重点关注" in comp                      # brands.yaml focus:true seeds

    # Toggle focus on a brand and back.
    r1 = client.post("/api/brands/Agresti/focus").json()
    assert r1["is_focus"] is True
    r2 = client.post("/api/brands/Agresti/focus").json()
    assert r2["is_focus"] is False


def test_search_and_notifications(client):
    res = client.get("/api/search", params={"q": "永发"}).json()
    assert res["results"]
    types = {r["type"] for r in res["results"]}
    assert "竞争对手" in types or "品牌档案" in types

    res2 = client.get("/api/search", params={"q": "保险"}).json()
    assert any(r["type"] == "产品" for r in res2["results"])

    notif = client.get("/api/notifications").json()
    assert notif["items"]
    assert notif["unread"] >= 1


def test_pptx_products_present(client):
    """Deck ingestion in seed → PPTX brands carry real market data."""
    prods = client.get("/products").text
    assert "Mango系列" in prods or "CL系列" in prods
    bench = client.get("/benchmark").text
    assert "德国百卫特" in bench                   # deck-declared counterpart pair


def test_agent_run_sse_stream(client, settings):
    """SSE endpoint replays steps of a finished run and closes with `done`."""
    from chubb_ci.schemas.models import AgentRun, AgentStepRecord

    with session_scope(settings) as s:
        run = AgentRun(workflow="scan", goal="t", status="done")
        s.add(run)
        s.commit()
        s.refresh(run)
        s.add(AgentStepRecord(run_id=run.id, node="规划", message="第一步"))
        s.add(AgentStepRecord(run_id=run.id, node="应用", message="第二步"))
        s.commit()
        run_id = run.id

    with client.stream("GET", f"/api/agent/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = "".join(chunk for chunk in resp.iter_text())
    assert body.count("event: step") == 2
    assert "第一步" in body and "第二步" in body
    assert "event: done" in body            # stream self-terminates for finished runs


def test_agent_run_sse_not_found(client):
    with client.stream("GET", "/api/agent/runs/99999/stream") as resp:
        body = "".join(resp.iter_text())
    assert "event: error" in body


def test_dashboard_data_and_csv(client):
    data = client.get("/api/dashboard-data").json()
    assert "kpis" in data and "trend" in data and "severity" in data

    csv_resp = client.get("/api/export/products.csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "product_name" in csv_resp.text
