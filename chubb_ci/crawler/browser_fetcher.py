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

from loguru import logger

from chubb_ci.crawler.fetch_base import FetchResult

# Login walls are only treated as blocks when they dominate the page; marketplaces
# always carry a "登录" link somewhere, so require strong markers.
_BLOCK_MARKERS = ("验证码", "captcha", "滑块验证", "人机验证", "访问过于频繁", "请登录后")

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
    ) -> None:
        self._user_agent = user_agent
        self._timeout_ms = timeout * 1000
        self._wait_after_load_ms = wait_after_load_ms
        self._scroll_rounds = scroll_rounds

    def fetch(self, url: str) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            logger.error("playwright not installed; run `uv sync --extra browser`")
            return FetchResult(url=url, ok=False, error=f"playwright missing: {exc}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=_STEALTH_ARGS)
                context = browser.new_context(
                    user_agent=self._user_agent,
                    locale="zh-CN",
                    viewport={"width": 1366, "height": 900},
                )
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

        if any(m in html[:8000] for m in _BLOCK_MARKERS):
            logger.warning("anti-bot challenge detected (browser) for {}", url)
            return FetchResult(url=url, ok=False, status=200, blocked=True, html=html)

        return FetchResult(url=url, ok=True, status=200, html=html)
