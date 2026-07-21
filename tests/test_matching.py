"""Tests for cross-platform SKU matching helpers (diff/matching.py)."""

from __future__ import annotations

import pytest

from chubb_ci.diff.matching import model_code, normalize_product_key


@pytest.mark.parametrize(
    "name,expected",
    [
        ("艾谱AE881全钢保险柜家用", "AE881"),
        ("得力4116G办公保险箱", "4116G"),
        ("虎王BGX-D1-800指纹保险柜", "BGX-D1-800"),
        # different platform titles, same model → same code (side-by-side compare)
        ("【京东自营】艾谱 AE881 保险箱 45cm", "AE881"),
        ("艾谱(AIPU)AE881家用办公防盗保险柜", "AE881"),
    ],
)
def test_model_code_extracts_sku(name, expected):
    assert model_code(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "永发H360系列保险柜",   # series name, no real SKU token
        "全钢家用保险箱",        # pure Chinese, no code
        "保险柜60cm高",          # height/dimension only, must not match
        "",
        None,
    ],
)
def test_model_code_none_for_seriesish(name):
    assert model_code(name) is None


def test_model_code_ignores_dimension_tokens():
    # 45CM / 60L should never be treated as a model code
    assert model_code("艾谱 45CM 60L 家用") is None


def test_normalize_key_still_independent_of_model_code():
    # matching by normalized key remains available for series-only products
    assert normalize_product_key("永发 H360-系列") == normalize_product_key("永发H360系列")
