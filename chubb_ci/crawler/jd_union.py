"""京东联盟开放平台 (JD Union, union.jd.com/openplatform) client — official price data.

Why JD Union and not 京东宙斯 (JOS): JOS merchant/ISV APIs expose *your own shop's*
data and require enterprise qualification; they cannot search competitors. JD Union's
``jd.union.open.goods.query`` is the official, low-barrier keyword search that returns
price / 30-day sales / shop / image for arbitrary JD listings — exactly the competitor
price feed this project needs. Registration: union.jd.com → 推广管理 → 导购媒体 (个人可
申请) → appkey/secretkey → `.env` CHUBB_JD_UNION_APP_KEY / CHUBB_JD_UNION_APP_SECRET.

Signing (京东开放平台通用): MD5(secret + k1v1k2v2… (ASCII-sorted) + secret), uppercase.
Gateway: https://api.jd.com/routerjson. The client degrades gracefully when keys are
missing (``available`` is False) — nothing else in the pipeline depends on it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

from chubb_ci.config.settings import Settings
from chubb_ci.schemas.models import ExtractedProduct

GATEWAY = "https://api.jd.com/routerjson"
_METHOD_GOODS_QUERY = "jd.union.open.goods.query"
_CST = timezone(timedelta(hours=8))  # gateway expects Beijing time


def sign_params(params: dict[str, str], secret: str) -> str:
    """京东开放平台 MD5 签名: md5(secret + sorted(k+v) + secret).upper()."""
    body = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hashlib.md5(f"{secret}{body}{secret}".encode("utf-8")).hexdigest().upper()


class JDUnionClient:
    """Minimal typed wrapper over the Union goods-query endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._key = settings.jd_union_app_key
        self._secret = settings.jd_union_app_secret
        self._timeout = settings.request_timeout

    @property
    def available(self) -> bool:
        return bool(self._key and self._secret)

    def _system_params(self, method: str, param_json: str) -> dict[str, str]:
        params = {
            "method": method,
            "app_key": self._key,
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
            "360buy_param_json": param_json,
        }
        params["sign"] = sign_params(params, self._secret)
        return params

    def query_goods(self, keyword: str, *, page_size: int = 20,
                    page_index: int = 1) -> list[ExtractedProduct]:
        """Keyword search → products with real JD price/sales/image/url.

        Returns [] on any failure (missing keys, HTTP error, non-200 union code) —
        marketplace failures are expected and must not break callers.
        """
        if not self.available:
            logger.info("JD Union 未配置 appkey/secret，跳过（见 .env.example）")
            return []
        param_json = json.dumps({"goodsReqDTO": {
            "keyword": keyword, "pageSize": page_size, "pageIndex": page_index,
        }}, ensure_ascii=False, separators=(",", ":"))
        try:
            resp = httpx.get(GATEWAY, params=self._system_params(_METHOD_GOODS_QUERY,
                                                                 param_json),
                             timeout=self._timeout)
            resp.raise_for_status()
            envelope = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("JD Union 请求失败（{}）: {}", keyword, exc)
            return []

        if "error_response" in envelope:
            logger.warning("JD Union 网关错误: {}", envelope["error_response"])
            return []
        try:
            payload = json.loads(
                envelope["jd_union_open_goods_query_responce"]["queryResult"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("JD Union 响应格式异常: {}", exc)
            return []
        if payload.get("code") != 200:
            logger.warning("JD Union 业务错误 code={} message={}",
                           payload.get("code"), payload.get("message"))
            return []
        return [p for p in (_to_product(item) for item in payload.get("data") or [])
                if p is not None]


def _to_product(item: dict) -> ExtractedProduct | None:
    """Union goods item → ExtractedProduct (deterministic mapping, no LLM)."""
    name = (item.get("skuName") or "").strip()
    if not name:
        return None
    price_info = item.get("priceInfo") or {}
    price = price_info.get("lowestPrice") or price_info.get("price")
    image = None
    image_list = ((item.get("imageInfo") or {}).get("imageList")) or []
    if image_list:
        image = image_list[0].get("url")
    return ExtractedProduct(
        product_name=name,
        category="保险柜",
        price=float(price) if price is not None else None,
        currency="CNY",
        sales_volume=item.get("inOrderCount30Days"),
        image_url=image,
        product_url=item.get("materialUrl"),
        source_url=GATEWAY,
    )
