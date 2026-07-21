"""Adapter for an external crawler microservice (e.g. ShilongLee/Crawler).

For platforms that cookie-Playwright can't reliably reach (Douyin/抖音商城, and Taobao's
stronger anti-bot), a dedicated signature-bypass crawler run as a separate service is the
pragmatic path. This adapter calls such a service's HTTP API and adapts the result to our
:class:`Fetcher` protocol / tile schema.

Disabled unless ``CHUBB_EXTERNAL_CRAWLER_URL`` is set. Not wired into any enabled source
in this round — see docs/DATA_SOURCES.md for how to stand one up.
"""

from __future__ import annotations

from loguru import logger

from chubb_ci.crawler.fetch_base import FetchResult


class CrawlerAPIFetcher:
    """Fetch via an external crawler service. Returns the raw JSON as the 'html' payload
    so a platform-specific tile/detail adapter can parse it (to be implemented per API)."""

    available = False  # flip on once a concrete API is wired

    def __init__(self, base_url: str, *, timeout: int = 30) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - stub
        logger.warning(
            "CrawlerAPIFetcher is a stub; configure a real crawler service + adapter. "
            "See docs/DATA_SOURCES.md. url={}", url)
        return FetchResult(url=url, ok=False,
                           error="external crawler adapter not implemented")
