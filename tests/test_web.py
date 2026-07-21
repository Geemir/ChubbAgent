"""Tests for the dashboard service and FastAPI routes (seeded temp DB)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import select  # noqa: E402

import chubb_ci.web.app as webapp  # noqa: E402
from chubb_ci.demo_seed import seed  # noqa: E402
from chubb_ci.storage.db import session_scope  # noqa: E402
from chubb_ci.storage.repositories import Repository  # noqa: E402
from chubb_ci.web.services import DashboardService, event_severity  # noqa: E402
from chubb_ci.schemas.models import DiffEvent, EventType, ProductRecord  # noqa: E402


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
        assert ins["total"] >= 1                 # pricing_anomaly / market_gap fire

        lb = svc.value_leaderboard()
        assert lb["rows"]
        assert any(r["is_own"] for r in lb["rows"])   # 集宝 present in the leaderboard
        assert lb["rows"] == sorted(lb["rows"], key=lambda r: r["avg_price"])

        profile = svc.brand_profile("永发 Yongfa")
        assert profile is not None
        assert profile["brand"] is not None      # §6 profile synced from brands.yaml
        assert profile["brand"].positioning
        assert profile["num_products"] >= 4

        # extended product columns
        prow = svc.products()["rows"][0]
        for col in ("capacity_l", "fire_hours", "security_score", "price_per_l",
                    "lead_time_days", "width_mm", "depth_mm", "height_mm"):
            assert col in prow


@pytest.fixture
def client(settings, monkeypatch):
    seed(settings, reset=True)
    monkeypatch.setattr(webapp, "get_settings", lambda: settings)
    with TestClient(webapp.app) as c:
        yield c


def test_pages_return_200(client):
    for path in ["/", "/reports", "/competitors", "/products", "/ingest",
                 "/benchmark", "/market", "/competitors/永发 Yongfa",
                 "/price-comparison", "/research-agent", "/settings", "/health",
                 "/research-agent/research", "/research-agent/enrich",
                 "/research-agent/ingest", "/research-agent/sentiment"]:
        resp = client.get(path)
        assert resp.status_code == 200, path


def test_agent_hub_lists_features_and_no_scan(client):
    html = client.get("/research-agent").text
    for title in ("品牌深挖", "竞品信息自动化搜集", "文档摄取", "舆情分析"):
        assert title in html
    assert "机会扫描" not in html  # scan removed
    assert "/research-agent/sentiment" in html


def test_agent_feature_subpage_renders_instructions(client):
    html = client.get("/research-agent/sentiment").text
    assert "使用说明" in html and "启动任务" in html
    assert "agent-console" in html  # shared run console included


def test_agent_unknown_feature_redirects(client):
    resp = client.get("/research-agent/nope", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/research-agent"


def test_agent_doc_upload_and_ingest_path_guard(client, settings):
    import base64

    # a tiny valid-enough .pptx (zip magic) — ingest parsing isn't exercised here
    raw = b"PK\x03\x04 fake pptx bytes"
    data_url = ("data:application/vnd.openxmlformats-officedocument."
                "presentationml.presentation;base64," + base64.b64encode(raw).decode())
    resp = client.post("/api/agent/upload", json={"data": data_url, "filename": "竞品分析.pptx"})
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert path.endswith(".pptx") and "uploads" in path

    from chubb_ci.web.app import _safe_ingest_path

    ok, resolved = _safe_ingest_path(path)          # uploaded file → allowed
    assert ok and resolved == str(__import__("pathlib").Path(path).resolve())
    assert not _safe_ingest_path("C:/Windows/system32/config")[0]  # traversal blocked
    assert not _safe_ingest_path("../../secret.pptx")[0]           # escape blocked
    assert not _safe_ingest_path(None)[0]

    # wrong type rejected
    assert client.post("/api/agent/upload",
                       json={"data": "data:text/plain;base64,QQ==", "filename": "x.txt"}
                       ).status_code == 415


def test_agent_start_rejects_bad_ingest_path(client):
    resp = client.post("/api/agent/start",
                       json={"workflow": "ingest", "path": "/etc/passwd"})
    assert resp.status_code == 400


# ---------------------------------------------------------------- interactive 对标
def test_benchmark_lists_and_compare(client, settings):
    with session_scope(settings) as session:
        lists = DashboardService(Repository(session), settings).benchmark_lists()
    assert lists["own"] and lists["competitors"]
    own_id = lists["own"][0]["id"]
    comp_id = lists["competitors"][0]["id"]

    resp = client.get("/api/benchmark/compare",
                      params={"own_id": own_id, "comp_id": comp_id})
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["own"]["name"] and detail["comp"]["name"]
    assert detail["calcs"]                                   # step-by-step rows
    labels = {c["label"] for c in detail["calcs"]}
    assert "价格差" in labels                                 # price-diff row present
    # a present calc shows a real formula (with numbers), not just a value
    priced = next((c for c in detail["calcs"] if c["label"] == "价格差"), None)
    assert priced and ("÷" in priced["formula"] or "缺少" in priced["formula"])

    assert client.get("/api/benchmark/compare",
                      params={"own_id": 999999, "comp_id": comp_id}).status_code == 404


def test_add_and_delete_own_product(client, settings):
    resp = client.post("/api/own-products", json={
        "product_name": "集宝测试款 X9", "price": "¥12,000", "width_mm": 400,
        "depth_mm": 400, "height_mm": 500, "weight_kg": 60, "gb_grade": "GB A级",
        "lead_time_days": 0})
    assert resp.status_code == 200
    pid = resp.json()["id"]
    with session_scope(settings) as session:
        from chubb_ci.schemas.models import OwnProduct

        rec = session.get(OwnProduct, pid)
        assert rec.price == 12000.0
        assert rec.capacity_l == 80.0            # 400×400×500 mm → 80 L
        assert rec.security_score is not None    # derived from GB A级
    # it shows in the picker list
    with session_scope(settings) as session:
        names = [o["name"] for o in
                 DashboardService(Repository(session), settings).benchmark_lists()["own"]]
        assert "集宝测试款 X9" in names

    assert client.delete(f"/api/own-products/{pid}").status_code == 200
    assert client.delete(f"/api/own-products/{pid}").status_code == 404


def test_old_market_urls_redirect(client):
    # merged into /market — old bookmarks 301 there; /promotions is gone
    for old in ["/market-map", "/price-changes", "/market-trends"]:
        resp = client.get(old, follow_redirects=False)
        assert resp.status_code == 301 and resp.headers["location"] == "/market", old
    assert client.get("/promotions").status_code == 404


def test_market_page_has_all_three_sections(client):
    html = client.get("/market").text
    assert "市场地图" in html and "价格变动" in html and "市场趋势" in html
    assert "capacityScatter" in html and "priceDirChart" in html  # both tabs' charts


def test_settings_status(client):
    st = client.get("/settings")
    assert st.status_code == 200
    assert "系统状态" in st.text
    # data coverage + source table render
    assert "真实数据覆盖" in st.text and "监控源" in st.text


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
        run = AgentRun(workflow="sentiment", goal="t", status="done")
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


def test_image_proxy_ssrf_guard(client):
    from chubb_ci.web.app import _img_url_safe

    assert _img_url_safe("https://imgservice1.suning.cn/a.jpg")
    assert not _img_url_safe("http://localhost:8000/secret")
    assert not _img_url_safe("http://127.0.0.1/x")
    assert not _img_url_safe("http://192.168.1.10/x")
    assert not _img_url_safe("file:///etc/passwd")
    # endpoint rejects internal hosts
    assert client.get("/api/img", params={"url": "http://127.0.0.1/x"}).status_code == 400


def test_products_page_has_image_column(client):
    html = client.get("/products").text
    assert "图片" in html and "/api/img?url=" in html or "product-row" in html


def test_products_table_keeps_actions_visible_and_links_details(client, settings):
    html = client.get("/products").text
    assert "sticky right-0" in html
    assert "title=\"详情\"" in html
    assert ">防火h <span" not in html
    assert ">防盗分 <span" not in html
    assert ">交期天 <span" not in html
    assert "<th class=\"text-left px-md py-md\">促销</th>" not in html

    with session_scope(settings) as session:
        from chubb_ci.schemas.models import ProductRecord

        product = session.exec(select(ProductRecord)).first()
        product_id = product.id
        product_name = product.product_name
    detail = client.get(f"/products/{product_id}")
    assert detail.status_code == 200
    assert product_name in detail.text
    assert "更新于" in detail.text


def test_enrich_endpoint_requires_product_id(client):
    response = client.post("/api/agent/start", json={"workflow": "enrich"})
    assert response.status_code == 400
    assert "product_id" in response.json()["error"]


def test_price_comparison_groups_same_model_across_channels(settings):
    """Same model_code on 京东 + 苏宁 (different titles/keys) → one row, 2 platforms."""
    seed(settings, reset=True)
    with session_scope(settings) as session:
        repo = Repository(session)
        repo.add_products([
            ProductRecord(company="艾谱", channel="京东", model_code="AE881",
                          product_name="艾谱AE881 京东自营", product_key="jd-ae881",
                          price=1999, product_url="https://item.jd.com/1.html"),
            ProductRecord(company="艾谱", channel="苏宁", model_code="AE881",
                          product_name="艾谱 AE881 苏宁易购", product_key="sn-ae881",
                          price=1799, product_url="https://product.suning.com/2.html"),
        ])
        svc = DashboardService(repo, settings)
        pc = svc.price_comparison()

        assert pc["multi_count"] >= 1
        # channels ordered with shopping platforms first
        assert pc["channels"].index("京东") < pc["channels"].index("苏宁")

        row = next(r for r in pc["rows"] if r["model"] == "AE881")
        assert row["n_platforms"] == 2
        assert row["min_price"] == 1799
        assert set(row["platforms"]) == {"京东", "苏宁"}
        assert round(row["spread_pct"]) == 11  # (1999-1799)/1799


def test_price_comparison_route_renders(client):
    resp = client.get("/price-comparison")
    assert resp.status_code == 200
    assert "多平台比价" in resp.text


# ---------------------------------------------------------------- mutable products
def test_product_create_update_delete(client, settings):
    # create (手动录入)
    resp = client.post("/api/products", json={
        "product_name": "测试安全柜 TS-100", "company": "测试品牌", "price": "¥2,999",
        "width_mm": 400, "depth_mm": 350, "height_mm": 500, "gb_grade": "GB A级"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    with session_scope(settings) as session:
        from chubb_ci.schemas.models import ProductRecord

        rec = session.get(ProductRecord, pid)
        assert rec.channel == "手动录入" and rec.source_name == "manual"
        assert rec.price == 2999.0                      # "¥2,999" coerced
        assert rec.model_code == "TS-100"               # derived from the name
        assert rec.capacity_l == 70.0                   # 400×350×500mm → 70 L
        assert rec.security_score is not None           # from GB A1

    # it shows on the products page with its id
    assert "测试安全柜 TS-100" in client.get("/products").text

    # update: price + clearing a field
    resp = client.patch(f"/api/products/{pid}", json={"price": 2599, "promotion": ""})
    assert resp.status_code == 200
    with session_scope(settings) as session:
        from chubb_ci.schemas.models import ProductRecord

        rec = session.get(ProductRecord, pid)
        assert rec.price == 2599.0 and rec.promotion is None

    # delete removes the whole history for that product
    resp = client.delete(f"/api/products/{pid}")
    assert resp.status_code == 200 and resp.json()["deleted"] >= 1
    assert "测试安全柜 TS-100" not in client.get("/products").text
    assert client.delete(f"/api/products/{pid}").status_code == 404


def test_product_delete_removes_all_history(client, settings):
    """Deleting must kill every snapshot row, or an older record resurfaces."""
    from chubb_ci.schemas.models import ProductRecord

    with session_scope(settings) as session:
        a = ProductRecord(company="X", product_name="老款100", product_key="k100", price=100)
        b = ProductRecord(company="X", product_name="老款100", product_key="k100", price=90)
        session.add(a)
        session.add(b)
        session.flush()
        pid = b.id
    resp = client.delete(f"/api/products/{pid}")
    assert resp.json()["deleted"] == 2


def test_ingest_page_and_parse_endpoint(client):
    assert "手动录入产品" in client.get("/ingest").text
    # too-short text is rejected
    assert client.post("/api/ingest/parse", json={"text": "短"}).status_code == 400
    # FakeLLM path returns an empty product list but proves the plumbing
    resp = client.post("/api/ingest/parse",
                       json={"text": "艾谱 AE881 保险柜 高60cm 净重52kg 到手价1899元"})
    assert resp.status_code == 200
    assert resp.json() == {"products": []}


def test_upload_roundtrip_and_guards(client):
    import base64

    # 1×1 transparent PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    resp = client.post("/api/upload", json={"data": data_url, "filename": "p.png"})
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert url.startswith("/uploads/") and url.endswith(".png")
    got = client.get(url)
    assert got.status_code == 200 and got.content == png
    # unsupported type + bad data are rejected
    assert client.post("/api/upload", json={"data": "data:text/html;base64,AAAA"}).status_code == 415
    assert client.post("/api/upload", json={"data": "data:image/png;base64,@@"}).status_code == 400
    assert client.get("/uploads/nope.png").status_code == 404


def test_dashboard_data_and_csv(client):
    data = client.get("/api/dashboard-data").json()
    assert "kpis" in data and "trend" in data and "severity" in data

    csv_resp = client.get("/api/export/products.csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "product_name" in csv_resp.text
