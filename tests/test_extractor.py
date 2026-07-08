"""Tests for extraction: happy path, JSON-in-noise, and the repair retry."""

from __future__ import annotations

from chubb_ci.config.sources import Source
from chubb_ci.extractor.extractor import extract_products
from chubb_ci.llm.fake import FakeLLM

SOURCE = Source(name="s", company="测试竞品", urls=["http://x"])
GOOD = '{"products": [{"product_name": "A系列", "price": 999, "gb_grade": "A"}]}'


def _extract(llm, text="页面正文"):
    return extract_products(
        llm, model="fake", source=SOURCE, url="http://x",
        page_text=text, domain_context="领域背景",
    )


def test_happy_path_parses_products():
    result = _extract(FakeLLM(responses=[GOOD]))
    assert result.ok and not result.repaired
    assert len(result.products) == 1
    assert result.products[0].product_name == "A系列"
    assert result.products[0].source_url == "http://x"  # backfilled


def test_json_embedded_in_prose_is_recovered():
    noisy = f"好的，这是结果：\n```json\n{GOOD}\n```\n希望有帮助"
    result = _extract(FakeLLM(responses=[noisy]))
    assert result.ok and len(result.products) == 1


def test_repair_retry_recovers_from_bad_first_response():
    llm = FakeLLM(responses=["这不是JSON，抱歉", GOOD])
    result = _extract(llm)
    assert result.ok and result.repaired
    assert len(result.products) == 1
    assert len(llm.calls) == 2  # initial + one repair


def test_gives_up_after_repair_still_invalid():
    llm = FakeLLM(responses=["garbage", "still garbage"])
    result = _extract(llm)
    assert not result.ok
    assert result.products == []
    assert result.error is not None


def test_empty_products_is_valid():
    result = _extract(FakeLLM(responses=['{"products": []}']))
    assert result.ok and result.products == []
