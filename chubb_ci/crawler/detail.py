"""Product detail-page spec extraction (规格参数) → structured fields.

Marketplace detail pages carry a key/value spec table. We collect pairs deterministically
(dl/dt-dd, table th/td, li-with-label) and map Chinese keys to our schema fields, so the
empty 容积/防火/防盗 columns can be filled. Derived metrics (volume, fire-hours, security
score) are computed by chubb_ci/normalize at ingest, not here.
"""

from __future__ import annotations

import re

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|千克|公斤|KG)")
_VOL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(l|L|升|升容量)")


def _collect_pairs(tree) -> dict[str, str]:
    pairs: dict[str, str] = {}

    def add(k: str, v: str) -> None:
        k, v = k.strip().strip("：: "), v.strip()
        if k and v and k not in pairs and len(k) <= 20:
            pairs[k] = v

    for dl in tree.css("dl"):
        dts, dds = dl.css("dt"), dl.css("dd")
        for dt, dd in zip(dts, dds):
            add(dt.text(strip=True), dd.text(separator=" ", strip=True))
    for row in tree.css("tr"):
        cells = row.css("th, td")
        if len(cells) >= 2:
            add(cells[0].text(strip=True), cells[1].text(separator=" ", strip=True))
    for li in tree.css("li"):
        label = li.css_first("span, .name, .title, em, i")
        if label is None:
            continue
        key = label.text(strip=True)
        full = li.text(separator=" ", strip=True)
        if key and full.startswith(key):
            add(key, full[len(key):])
    return pairs


def _dims_mm(value: str) -> tuple[float, float, float] | None:
    """Pull the first three numbers as W/D/H (tolerates 宽45×深39×高60 / 420*380*450)."""
    nums = [float(x) for x in _NUM_RE.findall(value)]
    if len(nums) < 3:
        return None
    w, d, h = nums[0], nums[1], nums[2]
    # cm → mm (safes are hundreds of mm; a <100 value is almost certainly cm)
    if max(w, d, h) < 100:
        w, d, h = w * 10, d * 10, h * 10
    return w, d, h


_IMG_JUNK = ("logo", "icon", "sprite", "placeholder", "loading", "blank", "pixel", "avatar")
_IMG_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "src")


def extract_main_image(html: str, base_url: str) -> str | None:
    """Best-effort main product image from a detail page (skips logos/icons/data-URIs).

    Prefers content-upload paths (wp-content/uploads, /upload, /uploads); falls back to
    the og:image meta tag, then the first non-junk <img>.
    """
    from urllib.parse import urljoin

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    og = tree.css_first('meta[property="og:image"]')
    if og and og.attributes.get("content"):
        return urljoin(base_url, og.attributes["content"])

    fallback: str | None = None
    for img in tree.css("img"):
        src = next((img.attributes.get(a) for a in _IMG_ATTRS if img.attributes.get(a)), None)
        if not src or src.startswith("data:"):
            continue
        low = src.lower()
        if any(j in low for j in _IMG_JUNK):
            continue
        url = urljoin(base_url, src)
        if any(p in low for p in ("wp-content/upload", "/upload", "/uploads", "/product")):
            return url                      # strong signal: a real content image
        fallback = fallback or url
    return fallback


def extract_specs(html: str) -> dict:
    """Return a dict of any recognized spec fields found on a detail page."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    pairs = _collect_pairs(tree)
    out: dict = {}

    for raw_key, value in pairs.items():
        key = raw_key.lower()
        # dims — Chinese 尺寸/规格 or English External/Overall size(mm), Dimension
        if (any(k in raw_key for k in ("尺寸", "长宽高", "规格", "外形", "外径", "外部尺寸"))
                or any(k in key for k in ("external size", "overall size", "outer size",
                                          "dimension", "product size", "size(mm)"))):
            if "packing" in key or "包装" in raw_key:  # ignore packing/carton size
                continue
            dims = _dims_mm(value)
            if dims and "width_mm" not in out:
                # order in listings is typically W×D×H; volume is order-independent
                out["width_mm"], out["depth_mm"], out["height_mm"] = dims
        # weight — 净重/重量 or N.W.(kgs)/Net weight (ignore G.W./gross where a net exists)
        if (any(k in raw_key for k in ("净重", "重量")) or "n.w" in key
                or "net weight" in key or "weight" in key) and "weight_kg" not in out:
            m = _WEIGHT_RE.search(value) or _NUM_RE.search(value)
            if m:
                out["weight_kg"] = float(m.group(1) if m.re is _WEIGHT_RE else m.group(0))
        if (any(k in raw_key for k in ("防火", "耐火")) or "fire" in key) and "fire_rating" not in out:
            out["fire_rating"] = value[:40]
        if (any(k in raw_key for k in ("防盗等级", "安全等级", "防盗", "认证等级"))
                or "security" in key or "grade" in key) and "gb_grade" not in out:
            out["gb_grade"] = value[:20]
        if (any(k in raw_key for k in ("容积", "容量")) or "volume" in key
                or "capacity" in key) and "capacity_l" not in out:
            m = _VOL_RE.search(value)
            if m:
                out["capacity_l"] = float(m.group(1))
        if (any(k in raw_key for k in ("锁具", "开锁", "开启方式", "锁类型"))
                or "lock" in key) and "lock_type" not in out:
            out["lock_type"] = value[:30]

    return out
