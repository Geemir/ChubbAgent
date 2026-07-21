"""Deterministic product-tile parser for marketplace listing pages.

Search/listing pages (苏宁/JD/Tmall) render regular product cards: image + title +
price (+ sales). We parse them with selectolax — no LLM — which is faster, cheaper,
and (unlike the trafilatura+LLM path) preserves **image URLs**.

Per-source CSS overrides live in the existing ``Source.selectors`` field
(``item``/``name``/``price``/``image``/``link``/``sales``); a generic fallback handles
sites without config. Search pages mix brands, so results are filtered to the source's
brand by normalized-name containment.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from pydantic import BaseModel

from chubb_ci.diff.matching import normalize_product_key

_PRICE_RE = re.compile(r"[￥¥]\s*(\d[\d,]*(?:\.\d+)?)")
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([wW万])?")
_IMG_ATTRS = ("src", "data-src", "data-original", "data-lazy-img", "data-img", "data-ks-lazyload")


class TileProduct(BaseModel):
    name: str
    price: float | None = None
    image_url: str | None = None
    product_url: str | None = None
    sales_volume: int | None = None


def _first_price(text: str, *, allow_bare: bool = False) -> float | None:
    """Price from text. With ``allow_bare`` (a dedicated price element), a number
    without ￥ is accepted; otherwise ￥ is required to avoid grabbing stray numbers."""
    m = _PRICE_RE.search(text or "")
    if not m and allow_bare:
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)", text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_sales(text: str) -> int | None:
    if not text:
        return None
    m = _NUM_RE.search(text)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if m.group(2):
        v *= 10_000
    return int(v) if v > 0 else None


def _abs_url(u: str | None, base_url: str) -> str | None:
    if not u:
        return None
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return urljoin(base_url, u)


def _img_src(node) -> str | None:
    for attr in _IMG_ATTRS:
        v = node.attributes.get(attr)
        if v and not v.startswith("data:"):
            return v
    return None


def _text(node) -> str:
    return node.text(separator=" ", strip=True) if node is not None else ""


def parse_tiles(
    html: str,
    *,
    selectors: dict[str, str] | None,
    brand: str,
    base_url: str,
) -> list[TileProduct]:
    """Extract product tiles from listing HTML, filtered to ``brand``."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    sel = selectors or {}
    brand_keys = [normalize_product_key(t) for t in re.split(r"[\s/]+", brand) if t]

    # Candidate tile containers.
    if sel.get("item"):
        items = tree.css(sel["item"])
    else:
        # Generic: any anchor wrapping an image is very likely a product card.
        items = [a for a in tree.css("a") if a.css_first("img") is not None]

    out: list[TileProduct] = []
    seen: set[str] = set()
    for it in items:
        img = it.css_first(sel["image"]) if sel.get("image") else it.css_first("img")
        name = ""
        if sel.get("name"):
            name = _text(it.css_first(sel["name"]))
        if not name and img is not None:
            name = (img.attributes.get("alt") or "").strip()
        if not name:
            link0 = it if it.tag == "a" else it.css_first("a")
            name = (link0.attributes.get("title") if link0 else "") or _text(it)[:80]
        name = name.strip()
        if not name:
            continue

        # brand filter — keep only this brand's products (search pages mix brands)
        nk = normalize_product_key(name)
        if brand_keys and not any(bk and bk in nk for bk in brand_keys):
            continue

        if sel.get("price"):
            price = _first_price(_text(it.css_first(sel["price"])), allow_bare=True)
        else:
            price = _first_price(_text(it))  # generic tile → require ￥

        link = it if it.tag == "a" else (
            it.css_first(sel["link"]) if sel.get("link") else it.css_first("a"))
        product_url = _abs_url(link.attributes.get("href") if link else None, base_url)
        image_url = _abs_url(_img_src(img) if img is not None else None, base_url)

        sales = None
        if sel.get("sales"):
            sales = _parse_sales(_text(it.css_first(sel["sales"])))

        key = product_url or nk
        if key in seen:
            continue
        seen.add(key)
        out.append(TileProduct(name=name, price=price, image_url=image_url,
                               product_url=product_url, sales_volume=sales))
    return out
