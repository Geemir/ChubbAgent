"""Tests for the 官网 catalog spider + English detail-spec parsing."""

from __future__ import annotations

from chubb_ci.crawler.catalog import parse_catalog_entries
from chubb_ci.crawler.detail import extract_main_image, extract_specs

# A category grid like AIPU's: <base href="/"> + relative product links repeated
# (an empty 'learn more' anchor and a titled one), thumbnails under /uploads/.
_LISTING = """
<html><head><base href="/"></head><body>
<div class="grid">
  <div class="card">
    <a href="products-info/70.html"><img data-src="/uploads/images/a.jpg"></a>
    <a href="products-info/70.html">learn more</a>
    <a href="products-info/70.html">Gun Safe 57NFG5B-E</a>
  </div>
  <div class="card">
    <a href="products-info/71.html"><img src="/uploads/images/b.jpg"></a>
    <a href="products-info/71.html">Biometric Gun Safe 57NFG5B-F</a>
  </div>
  <a href="/about.html">About us</a>
  <a href="products/8.html">Next category</a>
</div></body></html>
"""

_DETAIL = """
<html><body><h1>Electronic Safe BGX-X1-30XR</h1>
<table>
 <tr><td>Material</td><td>Steel</td></tr>
 <tr><td>External size(mm)</td><td>320*400*310</td></tr>
 <tr><td>Door thickness(mm)</td><td>8</td></tr>
 <tr><td>N.W.(kgs)</td><td>31</td></tr>
 <tr><td>Packing size(mm)</td><td>360*450*360</td></tr>
</table></body></html>
"""


def test_catalog_respects_base_href_and_dedups():
    res = parse_catalog_entries(
        _LISTING, "https://x.com/products/1.html", product_href=r"products-info/\d+")
    urls = {e.url for e in res.entries}
    # <base href="/"> → resolves to site root, NOT /products/products-info/...
    assert "https://x.com/products-info/70.html" in urls
    assert "https://x.com/products-info/71.html" in urls
    assert not any("products/products-info" in u for u in urls)
    assert len(res.entries) == 2  # two distinct products, deduped across repeated anchors


def test_catalog_picks_titled_name_over_junk_and_gets_image():
    res = parse_catalog_entries(
        _LISTING, "https://x.com/products/1.html", product_href=r"products-info/\d+")
    e = next(e for e in res.entries if e.url.endswith("70.html"))
    assert e.name == "Gun Safe 57NFG5B-E"          # not "learn more"
    assert e.image_url == "https://x.com/uploads/images/a.jpg"


def test_extract_specs_english_table():
    specs = extract_specs(_DETAIL)
    assert specs["width_mm"] == 320.0
    assert specs["depth_mm"] == 400.0
    assert specs["height_mm"] == 310.0
    assert specs["weight_kg"] == 31.0            # N.W.(kgs), not packing size


def test_extract_specs_ignores_packing_size():
    # packing/carton size must not overwrite the real external dims
    specs = extract_specs(_DETAIL)
    assert (specs["width_mm"], specs["depth_mm"], specs["height_mm"]) == (320.0, 400.0, 310.0)


def test_extract_main_image_prefers_og_then_content_over_logo():
    html = ('<html><head><meta property="og:image" content="/wp-content/uploads/x.jpg">'
            '</head><body><img src="/img/logo.png"><img src="/upload/real-600.jpg">'
            '</body></html>')
    assert extract_main_image(html, "https://f.de/produkt/a/") == "https://f.de/wp-content/uploads/x.jpg"


def test_extract_main_image_skips_logos_and_data_uris():
    html = ('<html><body><img src="data:image/gif;base64,AAAA">'
            '<img src="/assets/icon-sprite.svg">'
            '<img data-src="/upload/images/photo.jpg"></body></html>')
    assert extract_main_image(html, "https://x.com/") == "https://x.com/upload/images/photo.jpg"
