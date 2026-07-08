"""Schema/model tests: validation, keying, and record conversion."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chubb_ci.config.sources import Source, load_sources
from chubb_ci.diff.matching import normalize_product_key
from chubb_ci.schemas.models import ExtractedProduct, ProductRecord, record_to_extracted


def test_extracted_defaults_and_key():
    p = ExtractedProduct(product_name="  摩根系列  ")
    assert p.currency == "CNY"
    assert p.key_features == []
    assert p.product_key() == normalize_product_key("摩根系列")


def test_extraction_rejects_missing_name():
    with pytest.raises(ValidationError):
        ExtractedProduct()  # product_name required


def test_record_roundtrip_preserves_content():
    rec = ProductRecord(
        product_name="A系列", price=1234.0, gb_grade="B",
        key_features=["指纹", "防撬"], currency="CNY",
    )
    back = record_to_extracted(rec)
    assert back.product_name == "A系列"
    assert back.price == 1234.0
    assert back.gb_grade == "B"
    assert back.key_features == ["指纹", "防撬"]


def test_source_requires_url():
    with pytest.raises(ValidationError):
        Source(name="x", company="c", urls=[])


def test_load_sources_applies_defaults(tmp_path):
    f = tmp_path / "sources.yaml"
    f.write_text(
        """
version: 1
defaults:
  currency: CNY
  channel: 官网
sources:
  - name: a
    company: 甲
    urls: ["http://a"]
  - name: b
    company: 乙
    channel: 天猫
    urls: ["http://b"]
""".strip(),
        encoding="utf-8",
    )
    sources = load_sources(f)
    assert sources[0].channel == "官网"   # from defaults
    assert sources[1].channel == "天猫"   # overridden
