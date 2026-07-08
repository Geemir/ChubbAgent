"""End-to-end offline pipeline test (no network, no API key).

Uses the local HTML fixtures + the demo FakeLLM to exercise
fetch → extract → diff → store → report, and asserts real change detection.
"""

from __future__ import annotations

from chubb_ci.demo import demo_fake_llm
from chubb_ci.pipeline import generate_daily, run_crawl
from chubb_ci.schemas.models import EventType
from chubb_ci.storage.db import session_scope
from chubb_ci.storage.repositories import Repository
from tests.conftest import write_sources


def test_first_crawl_is_baseline_no_events(settings):
    write_sources(settings.sources_path, "competitor_v1.html")
    llm = demo_fake_llm()
    summary = run_crawl(settings, kind="demo", llm=llm)
    assert summary.sources_ok == 1
    assert summary.products_extracted == 3
    assert summary.events_detected == 0  # first snapshot = baseline


def test_unchanged_second_crawl_is_skipped(settings):
    write_sources(settings.sources_path, "competitor_v1.html")
    llm = demo_fake_llm()
    run_crawl(settings, kind="demo", llm=llm)
    summary = run_crawl(settings, kind="demo", llm=llm)  # identical content
    assert summary.sources_skipped == 1
    assert summary.products_extracted == 0


def test_changed_second_crawl_detects_events(settings):
    write_sources(settings.sources_path, "competitor_v1.html")
    llm = demo_fake_llm()
    run_crawl(settings, kind="demo", llm=llm)  # baseline v1

    override = {_v1_path(): _v2_path()}
    summary = run_crawl(settings, kind="demo", llm=llm, override_urls=override)

    assert summary.events_detected >= 3
    with session_scope(settings) as session:
        events = Repository(session).events_for_run(summary.run_id)
    types = {e.event_type for e in events}
    assert EventType.PRICE_CHANGE.value in types      # A: 1999 -> 1799
    assert EventType.DISCONTINUED.value in types      # C removed
    assert EventType.NEW_PRODUCT.value in types       # D added

    # And a daily report is produced from those events.
    draft = generate_daily(settings, run_id=summary.run_id, llm=llm)
    assert draft.num_events == summary.events_detected
    assert "每日速报" in draft.title


def _v1_path() -> str:
    from tests.conftest import FIXTURES

    return (FIXTURES / "competitor_v1.html").as_posix()


def _v2_path() -> str:
    from tests.conftest import FIXTURES

    return (FIXTURES / "competitor_v2.html").as_posix()
