"""Tests for the deterministic standardization engine (chubb_ci/normalize).

Test values include the exact formats found in ChubbProductsList.xlsx and
AnalyzeInformation.md.
"""

from __future__ import annotations

import pytest

from chubb_ci.normalize import (
    fire_hours,
    price_per_fire_hour,
    price_per_kg,
    price_per_l,
    security_score,
    value_for_money,
    value_index,
    volume_l,
)


# ---------------------------------------------------------------- fire hours
@pytest.mark.parametrize("text,expected", [
    ("UL 1h", 1.0),
    ("UL 2h", 2.0),
    ("UL 90min", 1.5),
    ("UL 120min", 2.0),
    ("UL 60min", 1.0),
    ("欧标30min", 0.5),
    ("欧标60min", 1.0),
    ("国标120min", 2.0),
    ("JIS 60min", 1.0),
    ("30分钟", 0.5),
    ("1小时", 1.0),
    ("EN15659/30min", 0.5),
    ("国标 120 分钟", 2.0),
])
def test_fire_hours_parses(text, expected):
    assert fire_hours(text) == expected


@pytest.mark.parametrize("text", [None, "", "-", " - ", "—", "无", "不防火"])
def test_fire_hours_none_cases(text):
    assert fire_hours(text) is None


# ------------------------------------------------------------ security score
@pytest.mark.parametrize("gb,euro,expected", [
    ("A", None, 1),
    ("B", None, 2),
    ("C", None, 3),
    ("CSP B", None, 2),            # xlsx format
    ("国标B级", None, 2),
    (None, "欧标S2级", 4),          # xlsx format
    (None, "欧标G1级", 5),          # xlsx format
    (None, "S1", 3),
    (None, "TL-15", 1),
    (None, "EN1143-1 III", 7),
    (None, "Grade II", 6),
    (None, "欧标 Grade I", 5),
    ("欧标S2级", None, 4),          # combined field landing in gb slot
    ("A", "欧标G1级", 5),           # both present → higher wins
    (None, None, None),
    ("-", "-", None),
])
def test_security_score(gb, euro, expected):
    assert security_score(gb, euro) == expected


# ------------------------------------------------------------------- metrics
def test_volume_from_dims_matches_xlsx():
    # Viper梵客 35: H450 × W445 × D390 → sheet says 78.0975 L
    assert volume_l(445, 390, 450) == pytest.approx(78.1, abs=0.05)


def test_volume_none_on_missing_or_invalid():
    assert volume_l(None, 390, 450) is None
    assert volume_l(0, 390, 450) is None
    assert volume_l(-1, 390, 450) is None


def test_unit_costs():
    assert price_per_l(11799, 78.1) == pytest.approx(151.1, abs=0.1)
    assert price_per_kg(11799, 42) == pytest.approx(280.9, abs=0.1)
    assert price_per_fire_hour(29900, 2.0) == 14950.0
    assert price_per_l(None, 78.1) is None
    assert price_per_l(11799, 0) is None


def test_value_indexes():
    # product cheaper per liter than benchmark → index > 1
    assert value_index(100.0, 120.0) == 1.2
    assert value_index(120.0, 100.0) == pytest.approx(0.83, abs=0.01)
    assert value_index(None, 100.0) is None
    # competitor pays more per liter than us → vfm > 1 (our advantage)
    assert value_for_money(180.0, 150.0) == 1.2
    assert value_for_money(0, 150.0) is None
