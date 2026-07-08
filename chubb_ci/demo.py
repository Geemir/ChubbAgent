"""Offline demo support: a scripted :class:`FakeLLM` for the local fixtures.

Lets ``chubb-ci crawl --demo`` run the full fetch→extract→diff→report pipeline with
no network and no API key, and visibly produce change events between two fixtures.
"""

from __future__ import annotations

import json

from chubb_ci.llm.fake import FakeLLM

# Baseline product set (matches tests/fixtures/competitor_v1.html).
_V1 = {
    "products": [
        {"product_name": "竞品保险柜 A系列", "category": "保险柜", "price": 1999,
         "currency": "CNY", "availability": "有货", "gb_grade": "A",
         "lock_type": "电子", "key_features": ["指纹解锁", "防撬"]},
        {"product_name": "竞品防火柜 B系列", "category": "防火柜", "price": 3999,
         "currency": "CNY", "availability": "有货", "fire_rating": "EN15659/30min"},
        {"product_name": "竞品金库门 C系列", "category": "金库门", "price": 8999,
         "currency": "CNY", "availability": "有货", "euro_grade": "EN1143-1 III"},
    ]
}

# Changed set (matches competitor_v2.html): A price drop + promo, C discontinued, D new.
_V2 = {
    "products": [
        {"product_name": "竞品保险柜 A系列", "category": "保险柜", "price": 1799,
         "currency": "CNY", "promotion": "618直降200", "promotion_end_date": "2026-06-18",
         "availability": "有货", "gb_grade": "A", "lock_type": "指纹",
         "key_features": ["指纹解锁", "防撬", "APP远程"]},
        {"product_name": "竞品防火柜 B系列", "category": "防火柜", "price": 3999,
         "currency": "CNY", "availability": "有货", "fire_rating": "EN15659/30min"},
        {"product_name": "竞品保管箱 D系列", "category": "保管箱", "price": 2599,
         "currency": "CNY", "availability": "预售", "gb_grade": "B"},
    ]
}


def _handler(system: str, user: str, json_mode: bool) -> str:
    variant = _V2 if "v2" in user else _V1
    return json.dumps(variant, ensure_ascii=False)


def demo_fake_llm() -> FakeLLM:
    """FakeLLM that returns V1 or V2 products based on the fixture's version marker."""
    return FakeLLM(handler=_handler)
