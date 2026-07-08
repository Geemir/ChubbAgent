"""Shared pytest fixtures: isolated settings + fresh database per test."""

from __future__ import annotations

from pathlib import Path

import pytest

from chubb_ci.config.settings import Settings
from chubb_ci.storage.db import _reset_engine_for_tests

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway data dir + sqlite db, using the fake LLM."""
    _reset_engine_for_tests()
    s = Settings(
        llm_provider="fake",
        data_dir=tmp_path / "data",
        db_url="",  # -> sqlite inside data_dir
        sources_file=tmp_path / "sources.yaml",
    )
    s.ensure_dirs()
    yield s
    _reset_engine_for_tests()


def write_sources(path: Path, fixture: str = "competitor_v1.html") -> None:
    """Write a minimal one-source sources.yaml pointing at a local fixture."""
    fixture_path = (FIXTURES / fixture).as_posix()
    path.write_text(
        f"""
version: 1
defaults:
  currency: CNY
sources:
  - name: test-competitor
    company: 测试竞品
    enabled: true
    fetcher: local
    page_type: product
    channel: 官网
    frequency: daily
    urls:
      - {fixture_path}
""".strip(),
        encoding="utf-8",
    )
