"""HTML → clean main text, and content hashing.

Extracting main text (dropping nav/footer/boilerplate) before sending to the LLM is
the single biggest token/cost lever, and it stabilizes the content hash so unchanged
pages are reliably skipped.
"""

from __future__ import annotations

import hashlib

from loguru import logger


def extract_main_text(html: str, url: str | None = None) -> str:
    """Return readable main text from raw HTML.

    Tries trafilatura (best boilerplate removal, good CJK support); falls back to a
    selectolax full-text dump; finally to the raw string.
    """
    if not html:
        return ""

    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if text and text.strip():
            return text.strip()
    except Exception as exc:  # noqa: BLE001 - fall through to selectolax
        logger.debug("trafilatura failed ({}); falling back to selectolax", exc)

    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in tree.css("script, style, noscript"):
            tag.decompose()
        body = tree.body or tree.root
        if body is not None:
            text = body.text(separator="\n", strip=True)
            if text:
                return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("selectolax fallback failed: {}", exc)

    return html.strip()


def content_hash(text: str) -> str:
    """Stable SHA-256 hex digest of normalized text (for change detection)."""
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
