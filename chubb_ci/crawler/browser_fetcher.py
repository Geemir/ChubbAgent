"""Headless-browser fetcher (Playwright) for JS-heavy / marketplace pages.

Best-effort by design: Chinese marketplaces (Tmall/JD) deploy aggressive anti-bot.
On a challenge we return ``blocked=True`` so the pipeline logs + skips rather than
crashing. Requires the optional ``browser`` extra + ``playwright install chromium``.

Marketplace-specific behavior:
- launches with automation flags disabled (basic stealth)
- scrolls the page a few times so lazily-loaded product tiles (prices!) render
- zh-CN locale + realistic UA
"""

from __future__ import annotations

import time

from loguru import logger

from chubb_ci.crawler.fetch_base import FetchResult

# Login walls are only treated as blocks when they dominate the page; marketplaces
# always carry a "登录" link somewhere, so require strong markers. Generic captcha
# markers are only trusted near the top of the page (footers can mention 验证码).
_BLOCK_MARKERS = ("验证码", "captcha", "滑块验证", "人机验证", "访问过于频繁", "请登录后")

# JD's soft anti-bot page ("很抱歉，由于访问频率过高…请稍后再试" inside a `_noDataCen`
# block) returns HTTP 200 with NO product tiles, deep in the body (~90 KB in). These
# unambiguous markers are scanned across the whole document, or we'd silently log 0.
_HARD_BLOCK_MARKERS = ("_noDataCen", "访问频率过高", "暂时无法访问", "请稍后再试")


def is_blocked(html: str) -> bool:
    """True if the HTML is an anti-bot / rate-limit page rather than real content.

    Generic captcha markers are only trusted near the top (footers mention 验证码);
    JD's hard block markers are scanned across the whole document (they sit ~90 KB in).
    """
    if not html:
        return False
    return (
        any(m in html[:8000] for m in _BLOCK_MARKERS)
        or any(m in html for m in _HARD_BLOCK_MARKERS)
    )

_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class BrowserFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: int = 30,
        # Marketplace tiles render asynchronously well after domcontentloaded;
        # empirically Suning needs ~4s + several scrolls before prices exist.
        wait_after_load_ms: int = 3500,
        scroll_rounds: int = 6,
        storage_state: str | None = None,
        # One retry absorbs transient nav timeouts / cold-start flakiness, which are
        # common on marketplace pages; a genuine block still returns fast (no retry).
        retries: int = 1,
        # JD/Tmall soft-block headless Chromium even with valid cookies; a visible
        # (headed) window passes their checks. Default headless for scheduled runs;
        # set CHUBB_BROWSER_HEADLESS=false for manual JD/Tmall crawls on a desktop.
        headless: bool = True,
    ) -> None:
        self._user_agent = user_agent
        self._timeout_ms = timeout * 1000
        self._wait_after_load_ms = wait_after_load_ms
        self._scroll_rounds = scroll_rounds
        self._storage_state = storage_state
        self._retries = max(0, retries)
        self._headless = headless

    def fetch(self, url: str) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            logger.error("playwright not installed; run `uv sync --extra browser`")
            return FetchResult(url=url, ok=False, error=f"playwright missing: {exc}")

        result = self._fetch_once(url)
        # Retry only on hard errors (timeout / crash) — never on a detected block.
        attempt = 0
        while not result.ok and not result.blocked and attempt < self._retries:
            attempt += 1
            time.sleep(1.5 * attempt)  # brief backoff
            logger.info("browser retry {}/{} for {}", attempt, self._retries, url)
            result = self._fetch_once(url)
        return result

    def _fetch_once(self, url: str) -> FetchResult:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self._headless, args=_STEALTH_ARGS)
                ctx_kwargs: dict = {
                    "user_agent": self._user_agent,
                    "locale": "zh-CN",
                    "viewport": {"width": 1366, "height": 900},
                }
                if self._storage_state:
                    ctx_kwargs["storage_state"] = self._storage_state  # logged-in session
                context = browser.new_context(**ctx_kwargs)
                # Basic stealth: hide the webdriver flag before any page script runs.
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(url, timeout=self._timeout_ms, wait_until="domcontentloaded")
                page.wait_for_timeout(self._wait_after_load_ms)
                # Scroll to trigger lazy-loaded tiles (marketplace prices render on scroll).
                for _ in range(self._scroll_rounds):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(500)
                html = page.content()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser fetch failed for {}: {}", url, exc)
            return FetchResult(url=url, ok=False, error=str(exc))

        if is_blocked(html):
            logger.warning("anti-bot challenge detected (browser) for {}", url)
            return FetchResult(url=url, ok=False, status=200, blocked=True, html=html)

        return FetchResult(url=url, ok=True, status=200, html=html)
