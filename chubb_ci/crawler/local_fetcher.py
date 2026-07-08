"""Local-file fetcher — reads HTML from disk for demos and offline tests."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from chubb_ci.crawler.fetch_base import FetchResult

# Repo root = three levels up (chubb_ci/crawler/local_fetcher.py).
_ROOT = Path(__file__).resolve().parents[2]


class LocalFetcher:
    """Treats each ``url`` as a filesystem path (absolute or repo-relative)."""

    def fetch(self, url: str) -> FetchResult:
        raw = url.replace("file://", "")
        path = Path(raw)
        if not path.is_absolute():
            path = _ROOT / raw
        if not path.exists():
            logger.warning("local fixture not found: {}", path)
            return FetchResult(url=url, ok=False, error=f"file not found: {path}")
        return FetchResult(url=url, ok=True, status=200, html=path.read_text(encoding="utf-8"))
