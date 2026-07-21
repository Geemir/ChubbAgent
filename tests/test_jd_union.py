"""Tests for the JD Union (京东联盟) official price client — offline, mocked HTTP."""

from __future__ import annotations

import hashlib
import json

import chubb_ci.crawler.jd_union as jd_union
from chubb_ci.crawler.jd_union import JDUnionClient, sign_params


def test_sign_matches_jd_md5_scheme():
    params = {"b": "2", "a": "1", "method": "jd.union.open.goods.query"}
    expected = hashlib.md5(
        "SECa1b2methodjd.union.open.goods.querySEC".encode()).hexdigest().upper()
    assert sign_params(params, "SEC") == expected


def test_unavailable_without_keys(settings):
    client = JDUnionClient(settings)          # settings fixture has no union keys
    assert not client.available
    assert client.query_goods("保险柜") == []


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - never raises here
        pass

    def json(self) -> dict:
        return self._payload


def _envelope(items: list[dict], code: int = 200) -> dict:
    return {"jd_union_open_goods_query_responce": {
        "queryResult": json.dumps({"code": code, "data": items}, ensure_ascii=False)}}


def test_query_goods_maps_items(settings, monkeypatch):
    settings.jd_union_app_key = "k"
    settings.jd_union_app_secret = "s"
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"], captured["params"] = url, params
        return _Resp(_envelope([{
            "skuName": "艾谱 AE881 全钢保险柜",
            "priceInfo": {"price": 2199.0, "lowestPrice": 1999.0},
            "inOrderCount30Days": 320,
            "materialUrl": "https://item.jd.com/100012345.html",
            "imageInfo": {"imageList": [{"url": "https://img.jd.com/ae881.jpg"}]},
        }, {"skuName": ""}]))  # nameless item must be dropped

    monkeypatch.setattr(jd_union.httpx, "get", fake_get)
    products = JDUnionClient(settings).query_goods("艾谱保险柜", page_size=5)

    assert captured["url"] == jd_union.GATEWAY
    assert captured["params"]["method"] == "jd.union.open.goods.query"
    assert "sign" in captured["params"]
    body = json.loads(captured["params"]["360buy_param_json"])
    assert body["goodsReqDTO"]["keyword"] == "艾谱保险柜"

    assert len(products) == 1
    p = products[0]
    assert p.price == 1999.0                          # lowestPrice preferred
    assert p.sales_volume == 320
    assert p.product_url.endswith("100012345.html")
    assert p.image_url.endswith("ae881.jpg")


def test_query_goods_handles_gateway_and_business_errors(settings, monkeypatch):
    settings.jd_union_app_key = "k"
    settings.jd_union_app_secret = "s"
    client = JDUnionClient(settings)

    monkeypatch.setattr(jd_union.httpx, "get",
                        lambda *a, **kw: _Resp({"error_response": {"code": "19"}}))
    assert client.query_goods("x") == []

    monkeypatch.setattr(jd_union.httpx, "get",
                        lambda *a, **kw: _Resp(_envelope([], code=403)))
    assert client.query_goods("x") == []
