"""Static HTTP fetcher (httpx) for brand 官网 and other server-rendered pages."""

from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from chubb_ci.crawler.fetch_base import FetchResult

# Substrings that suggest an anti-bot / verification interstitial.
_BLOCK_MARKERS = ("验证", "captcha", "滑块", "人机验证", "robot check", "访问过于频繁")

_META_CHARSET = re.compile(rb'charset=["\']?\s*([a-zA-Z0-9_\-]+)')


def _decode_html(resp: httpx.Response) -> str:
    """Decode HTML robustly, honoring a ``<meta charset>`` when the HTTP header omits it.

    Many Chinese sites serve GB2312/GBK without a Content-Type charset, which httpx
    then mis-decodes as UTF-8 (mojibake). Sniff the meta charset as a fallback.
    """
    if resp.charset_encoding:  # charset declared in the Content-Type header
        return resp.text
    raw = resp.content
    match = _META_CHARSET.search(raw[:2048])
    if match:
        enc = match.group(1).decode("ascii", "ignore").lower()
        enc = {"gb2312": "gb18030", "gbk": "gb18030"}.get(enc, enc)  # superset for safety
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            pass
    return resp.text


class StaticFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: int = 30,
        max_retries: int = 3,
        respect_robots: bool = True,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._respect_robots = respect_robots
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ---------------------------------------------------------------- robots
    def _allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(root, ...)  # type: ignore[arg-type]
        if rp is ...:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.set_url(urljoin(root, "/robots.txt"))
                rp.read()
            except Exception:  # noqa: BLE001 - robots absent/unreachable => allow
                rp = None
            self._robots_cache[root] = rp
        if rp is None:
            return True
        return rp.can_fetch(self._headers["User-Agent"], url)

    # ----------------------------------------------------------------- fetch
    def fetch(self, url: str) -> FetchResult:
        if not self._allowed(url):
            logger.warning("robots.txt disallows {}", url)
            return FetchResult(url=url, ok=False, error="disallowed by robots.txt")

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=15),
        )
        def _get() -> httpx.Response:
            with httpx.Client(
                headers=self._headers, timeout=self._timeout, follow_redirects=True
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp

        try:
            resp = _get()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            blocked = status in (403, 429)
            logger.warning("HTTP {} for {}", status, url)
            return FetchResult(url=url, ok=False, status=status, blocked=blocked, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch failed for {}: {}", url, exc)
            return FetchResult(url=url, ok=False, error=str(exc))

        text = _decode_html(resp)
        if any(m in text[:4000] for m in _BLOCK_MARKERS):
            logger.warning("anti-bot interstitial detected for {}", url)
            return FetchResult(url=url, ok=False, status=resp.status_code, blocked=True, html=text)

        return FetchResult(url=url, ok=True, status=resp.status_code, html=text)
