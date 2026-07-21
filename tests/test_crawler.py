"""Tests for crawler content handling (encoding robustness, main-text extraction)."""

from __future__ import annotations

import httpx

from chubb_ci.crawler.content import content_hash, extract_main_text
from chubb_ci.crawler.static_fetcher import _decode_html


def test_decode_html_gbk_meta_without_header_charset():
    # GBK/GB2312 page that declares charset only in a <meta>, not the HTTP header.
    html = '<html><head><meta charset="gb2312"></head><body>永发保险柜</body></html>'
    resp = httpx.Response(200, content=html.encode("gb18030"),
                          headers={"content-type": "text/html"})
    out = _decode_html(resp)
    assert "永发保险柜" in out


def test_decode_html_respects_header_charset():
    resp = httpx.Response(200, content="迪堡智能保险柜".encode("utf-8"),
                          headers={"content-type": "text/html; charset=utf-8"})
    assert "迪堡智能保险柜" in _decode_html(resp)


def test_extract_main_text_strips_boilerplate():
    html = "<html><body><nav>菜单</nav><main><h1>产品中心</h1>" \
           "<p>防火箱系列 保险柜</p></main><footer>版权</footer></body></html>"
    text = extract_main_text(html, url="http://example.com")
    assert "产品中心" in text
    assert "保险柜" in text


def test_content_hash_stable_and_whitespace_insensitive():
    a = content_hash("产品中心\n  保险柜  \n")
    b = content_hash("产品中心\n保险柜\n")
    assert a == b


def _fetcher(**kw):
    from chubb_ci.crawler.browser_fetcher import BrowserFetcher
    return BrowserFetcher(user_agent="ua", **kw)


def test_browser_fetch_retries_transient_error(monkeypatch):
    from chubb_ci.crawler.fetch_base import FetchResult

    f = _fetcher(retries=2)
    calls = {"n": 0}

    def fake_once(url):
        calls["n"] += 1
        if calls["n"] < 3:
            return FetchResult(url=url, ok=False, error="timeout")
        return FetchResult(url=url, ok=True, status=200, html="<html>ok</html>")

    monkeypatch.setattr(f, "_fetch_once", fake_once)
    monkeypatch.setattr("chubb_ci.crawler.browser_fetcher.time.sleep", lambda *_: None)
    res = f.fetch("http://x")
    assert res.ok and calls["n"] == 3


def test_is_blocked_detects_jd_ratelimit_deep_in_body():
    from chubb_ci.crawler.browser_fetcher import is_blocked

    # JD's block sits ~90 KB into the page inside a `_noDataCen` div — must still catch it.
    html = "<html><body>" + ("<div class='pad'></div>" * 4000) + \
           "<div class='_noDataCen_ce5n7_6'>很抱歉，由于访问频率过高，暂时无法访问，请稍后再试！</div></body></html>"
    assert len(html) > 8000
    assert is_blocked(html)


def test_is_blocked_ignores_normal_marketplace_page():
    from chubb_ci.crawler.browser_fetcher import is_blocked

    html = "<html><body><li class='gl-item'><div class='p-price'>¥999</div></li></body></html>"
    assert not is_blocked(html)


def test_browser_fetch_does_not_retry_on_block(monkeypatch):
    from chubb_ci.crawler.fetch_base import FetchResult

    f = _fetcher(retries=3)
    calls = {"n": 0}

    def fake_once(url):
        calls["n"] += 1
        return FetchResult(url=url, ok=False, status=200, blocked=True, html="验证码")

    monkeypatch.setattr(f, "_fetch_once", fake_once)
    res = f.fetch("http://x")
    assert res.blocked and calls["n"] == 1  # blocked → no retry
