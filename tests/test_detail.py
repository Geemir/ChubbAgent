"""Tests for detail-page spec extraction + normalization."""

from __future__ import annotations

from chubb_ci.crawler.detail import extract_specs
from chubb_ci.normalize import fire_hours, security_score, volume_l

DETAIL_TABLE = """
<html><body>
<table>
  <tr><th>外形尺寸</th><td>420×380×450mm</td></tr>
  <tr><th>净重</th><td>约 42 kg</td></tr>
  <tr><th>防火等级</th><td>欧标30min</td></tr>
  <tr><th>防盗等级</th><td>国标A级</td></tr>
  <tr><th>开锁方式</th><td>指纹+密码</td></tr>
</table>
</body></html>
"""

DETAIL_DL_CM = """
<html><body>
<dl><dt>产品尺寸</dt><dd>宽45×深39×高60 cm</dd></dl>
<dl><dt>容积</dt><dd>78L</dd></dl>
</body></html>
"""


def test_extract_specs_table():
    specs = extract_specs(DETAIL_TABLE)
    assert specs["width_mm"] == 420 and specs["depth_mm"] == 380 and specs["height_mm"] == 450
    assert specs["weight_kg"] == 42.0
    assert "30min" in specs["fire_rating"]
    assert specs["gb_grade"].startswith("国标A")
    assert "指纹" in specs["lock_type"]
    # normalization downstream
    assert fire_hours(specs["fire_rating"]) == 0.5
    assert security_score(specs["gb_grade"]) == 1
    assert volume_l(specs["width_mm"], specs["depth_mm"], specs["height_mm"]) == 71.8


def test_extract_specs_dl_cm_conversion():
    specs = extract_specs(DETAIL_DL_CM)
    # cm → mm
    assert specs["width_mm"] == 450 and specs["height_mm"] == 600
    assert specs["capacity_l"] == 78.0


def test_extract_specs_empty():
    assert extract_specs("<html><body><p>无参数</p></body></html>") == {}
