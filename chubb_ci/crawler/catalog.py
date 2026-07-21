"""Catalog spider: enumerate EVERY product on a competitor 官网, not just the seed page.

官网 landing pages list a handful of series; the full catalog lives behind category /
detail links. Given one or more listing/category pages, this deterministically collects
every product-detail link (name + thumbnail + URL) so extraction covers the whole range.
Prices are irrelevant here — the goal is complete product coverage with specs from the
detail page (parsed by chubb_ci.crawler.detail.extract_specs).

Per-source config lives in ``Source.selectors``:
  product_href : regex a detail-page href must match (e.g. ``products-info/\\d+`` ,
                 ``product_view\\.php`` , ``/produkt/``). REQUIRED for a catalog source.
  image        : optional CSS for the card thumbnail (defaults to nearest <img>).
  name         : optional CSS for the card name  (defaults to the anchor's own text).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-img", "data-lazyload", "src")
# Anchor text that is navigation/boilerplate rather than a product name.
_JUNK_NAMES = {"learn more", "more", "详情", "查看详情", "read more", "详细", "了解更多", ""}


@dataclass
class CatalogEntry:
    name: str
    url: str
    image_url: str | None = None


@dataclass
class CatalogResult:
    entries: list[CatalogEntry] = field(default_factory=list)
    #: category/pagination links worth following to reach more products
    follow: list[str] = field(default_factory=list)


def _abs(href: str | None, base: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
        return None
    return urljoin(base, href)


def _host(u: str) -> str:
    return urlparse(u).netloc.split(":")[0].lower().removeprefix("www.")


def _same_host(url: str, base: str) -> bool:
    try:  # treat www.x and x as the same site
        return _host(url) == _host(base)
    except ValueError:
        return False


def _img_near(anchor) -> str | None:
    """First lazy/real image inside the anchor or its parent card."""
    for scope in (anchor, anchor.parent, getattr(anchor.parent, "parent", None)):
        if scope is None:
            continue
        img = scope.css_first("img")
        if img is not None:
            for attr in _LAZY_ATTRS:
                v = img.attributes.get(attr)
                if v and not v.startswith("data:"):
                    return v
    return None


def parse_catalog_entries(
    html: str,
    base_url: str,
    *,
    product_href: str,
    name_sel: str | None = None,
    image_sel: str | None = None,
    follow_href: str | None = None,
) -> CatalogResult:
    """Extract product-detail entries (name+url+image) from one listing/category page.

    Products are found by anchors whose href matches ``product_href``. The best name for
    a URL is the longest non-junk anchor text pointing at it (grids repeat the link with
    an empty 'learn more' anchor and a real titled one).
    """
    tree = HTMLParser(html or "")
    # Honor <base href> — many CN sites use <base href="/"> so their relative links
    # (products-info/46.html) resolve against the site root, not the current path.
    base_tag = tree.css_first("base")
    if base_tag and base_tag.attributes.get("href"):
        base_url = urljoin(base_url, base_tag.attributes["href"])
    href_re = re.compile(product_href, re.I)
    by_url: dict[str, CatalogEntry] = {}

    for a in tree.css("a"):
        url = _abs(a.attributes.get("href"), base_url)
        if not url or not href_re.search(url) or not _same_host(url, base_url):
            continue
        name = ""
        if name_sel:
            n = a.css_first(name_sel)
            name = n.text(strip=True) if n else ""
        name = (name or a.text(strip=True)).strip()
        if name.lower() in _JUNK_NAMES:
            name = ""
        image = None
        if image_sel:
            im = a.css_first(image_sel) or (a.parent.css_first(image_sel) if a.parent else None)
            if im is not None:
                for attr in _LAZY_ATTRS:
                    if im.attributes.get(attr):
                        image = im.attributes[attr]
                        break
        image = image or _img_near(a)
        image = _abs(image, base_url)

        cur = by_url.get(url)
        if cur is None:
            by_url[url] = CatalogEntry(name=name, url=url, image_url=image)
        else:  # merge: keep the most informative name/image
            if len(name) > len(cur.name):
                cur.name = name
            if not cur.image_url and image:
                cur.image_url = image

    follow: list[str] = []
    if follow_href:
        f_re = re.compile(follow_href, re.I)
        seen = set()
        for a in tree.css("a"):
            u = _abs(a.attributes.get("href"), base_url)
            if u and u not in seen and f_re.search(u) and _same_host(u, base_url):
                seen.add(u)
                follow.append(u)

    return CatalogResult(entries=list(by_url.values()), follow=follow)
