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
