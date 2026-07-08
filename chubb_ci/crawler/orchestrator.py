"""Fetcher selection + fetch-and-clean for a single (source, url) pair."""

from __future__ import annotations

from pydantic import BaseModel

from chubb_ci.config.settings import Settings
from chubb_ci.config.sources import FetcherKind, Source
from chubb_ci.crawler.browser_fetcher import BrowserFetcher
from chubb_ci.crawler.content import content_hash, extract_main_text
from chubb_ci.crawler.fetch_base import Fetcher, FetchResult
from chubb_ci.crawler.local_fetcher import LocalFetcher
from chubb_ci.crawler.static_fetcher import StaticFetcher


class CleanedPage(BaseModel):
    """A fetched page plus its cleaned main text and content hash."""

    fetch: FetchResult
    main_text: str = ""
    content_hash: str = ""


def make_fetcher(source: Source, settings: Settings) -> Fetcher:
    """Return the fetcher backend declared by the source."""
    if source.fetcher is FetcherKind.LOCAL:
        return LocalFetcher()
    if source.fetcher is FetcherKind.BROWSER:
        return BrowserFetcher(
            user_agent=settings.user_agent, timeout=settings.request_timeout
        )
    return StaticFetcher(
        user_agent=settings.user_agent,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        respect_robots=settings.respect_robots,
    )


def fetch_and_clean(fetcher: Fetcher, url: str, settings: Settings) -> CleanedPage:
    """Fetch one URL and produce cleaned text + hash (bounded by max_extract_chars)."""
    result = fetcher.fetch(url)
    if not result.ok or not result.html:
        return CleanedPage(fetch=result)

    text = extract_main_text(result.html, url=url)
    if settings.max_extract_chars and len(text) > settings.max_extract_chars:
        text = text[: settings.max_extract_chars]
    return CleanedPage(fetch=result, main_text=text, content_hash=content_hash(text))
