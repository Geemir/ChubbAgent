"""Tests for marketplace session helpers."""

from __future__ import annotations

from chubb_ci.crawler.session import (
    LOGIN_URLS,
    load_state_for,
    platform_for_url,
    session_path,
)


def test_platform_for_url():
    assert platform_for_url("https://search.jd.com/Search?keyword=x") == "jd"
    assert platform_for_url("https://item.jd.com/1.html") == "jd"
    assert platform_for_url("https://list.tmall.com/search_product.htm") == "taobao"
    assert platform_for_url("https://s.taobao.com/search") == "taobao"
    assert platform_for_url("https://search.suning.com/x/") == "suning"
    assert platform_for_url("https://www.yongfagroup.com/") is None


def test_login_urls_cover_platforms():
    for p in ("jd", "taobao", "suning"):
        assert p in LOGIN_URLS


def test_load_state_for(settings):
    # No session file yet → None.
    assert load_state_for("https://search.jd.com/x", settings) is None
    # Create one → path returned.
    p = session_path("jd", settings)
    p.write_text("{}", encoding="utf-8")
    assert load_state_for("https://item.jd.com/1.html", settings) == str(p)
    # Unknown platform → None even if some session exists.
    assert load_state_for("https://example.com/", settings) is None
