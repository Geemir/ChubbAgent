"""Tests for the marketplace tile parser (images + price + URL + brand filter)."""

from __future__ import annotations

from chubb_ci.crawler.tiles import parse_tiles

SUNING = """
<html><body>
<div class="product-box">
  <a href="//product.suning.com/0010328655/12442908158.html">
    <img data-src="//imgservice1.suning.cn/uimg1/b2c/a.jpg" alt="得力AE881指纹密码保管箱H360高36CM"/>
  </a>
  <div class="price-box">¥999.00</div>
</div>
<div class="product-box">
  <a href="//product.suning.com/0010328655/999.html">
    <img src="https://imgservice1.suning.cn/b.jpg" alt="得力4116G指纹密码保险柜H610"/>
  </a>
  <div class="price-box">¥2,499.00</div>
</div>
<div class="product-box">
  <a href="//product.suning.com/x/other.html">
    <img src="https://x/c.jpg" alt="虎王家用小型保险箱"/>
  </a>
  <div class="price-box">¥599.00</div>
</div>
</body></html>
"""

SUNING_SEL = {"item": ".product-box", "price": ".price-box", "image": "img", "link": "a"}

JD = """
<html><body>
<li class="gl-item">
  <div class="p-img"><a href="//item.jd.com/100.html"><img data-lazy-img="//img10.360buyimg.com/x.jpg"/></a></div>
  <div class="p-name"><a href="//item.jd.com/100.html"><em>永发 家用保险柜 60cm</em></a></div>
  <div class="p-price"><strong><i>1899.00</i></strong></div>
  <div class="p-commit"><strong><a>已有 500 人评价</a></strong></div>
</li>
</body></html>
"""
JD_SEL = {"item": "li.gl-item", "name": ".p-name em", "price": ".p-price",
          "image": ".p-img img", "link": ".p-name a", "sales": ".p-commit strong"}


def test_suning_tiles_price_image_url():
    tiles = parse_tiles(SUNING, selectors=SUNING_SEL, brand="得力 Deli",
                        base_url="https://search.suning.com/x/")
    assert len(tiles) == 2                       # 虎王 tile filtered out (brand mismatch)
    t = tiles[0]
    assert t.name.startswith("得力AE881")
    assert t.price == 999.0
    assert t.image_url == "https://imgservice1.suning.cn/uimg1/b2c/a.jpg"  # //→https, data-src
    assert t.product_url.startswith("https://product.suning.com/")
    assert tiles[1].price == 2499.0              # comma stripped


def test_brand_filter_excludes_other_brands():
    tiles = parse_tiles(SUNING, selectors=SUNING_SEL, brand="虎王 Huwang",
                        base_url="https://search.suning.com/x/")
    assert len(tiles) == 1
    assert "虎王" in tiles[0].name


def test_jd_tiles_with_sales():
    tiles = parse_tiles(JD, selectors=JD_SEL, brand="永发 Yongfa",
                        base_url="https://search.jd.com/")
    assert len(tiles) == 1
    t = tiles[0]
    assert t.price == 1899.0
    assert t.image_url.endswith("x.jpg") and t.image_url.startswith("https://")
    assert t.sales_volume == 500
    assert t.product_url.startswith("https://item.jd.com/")


def test_generic_fallback_without_selectors():
    tiles = parse_tiles(SUNING, selectors=None, brand="得力 Deli",
                        base_url="https://search.suning.com/x/")
    assert len(tiles) == 2                       # anchors-with-images heuristic
    assert all(t.image_url for t in tiles)


def test_empty_html_yields_nothing():
    assert parse_tiles("<html></html>", selectors=SUNING_SEL, brand="X",
                       base_url="http://x") == []
