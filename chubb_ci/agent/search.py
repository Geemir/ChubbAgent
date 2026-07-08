"""China-accessible web-search providers behind the SearchProvider protocol.

- **BochaSearch** (博查, api.bochaai.com) — mainland-reachable search API; set
  ``CHUBB_SEARCH_PROVIDER=bocha`` + ``CHUBB_SEARCH_API_KEY``.
- **NoSearch** — explicit stand-in when no key is configured: returns nothing and the
  flows degrade gracefully (research requires a --url, discovery reports the limitation).
"""

from __future__ import annotations

import httpx
from loguru import logger

from chubb_ci.agent.state import SearchHit
from chubb_ci.config.settings import Settings


class NoSearch:
    """No search backend configured."""

    available = False

    def search(self, query: str, *, top_k: int = 10) -> list[SearchHit]:
        logger.warning("search requested but no provider configured (query: {})", query)
        return []


class BochaSearch:
    """博查 web-search API (OpenAI-of-search style, mainland-reachable)."""

    available = True

    def __init__(self, api_key: str, timeout: int = 20) -> None:
        self._key = api_key
        self._timeout = timeout

    def search(self, query: str, *, top_k: int = 10) -> list[SearchHit]:
        try:
            resp = httpx.post(
                "https://api.bochaai.com/v1/web-search",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"query": query, "count": top_k, "summary": True},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            pages = (resp.json().get("data", {}).get("webPages", {}) or {}).get("value", []) or []
            return [
                SearchHit(
                    title=p.get("name", ""),
                    url=p.get("url", ""),
                    snippet=p.get("summary") or p.get("snippet", ""),
                )
                for p in pages
            ]
        except Exception as exc:  # noqa: BLE001 - searches are best-effort
            logger.warning("bocha search failed for '{}': {}", query, exc)
            return []


def build_search(settings: Settings):
    """Return the configured SearchProvider."""
    provider = settings.search_provider.strip().lower()
    if provider == "bocha" and settings.search_api_key:
        return BochaSearch(settings.search_api_key)
    return NoSearch()
