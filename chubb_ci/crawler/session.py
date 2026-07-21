"""Marketplace login sessions (Playwright storage_state) for authenticated crawling.

JD/Tmall gate prices behind a login wall. We persist a logged-in session per platform
as a Playwright ``storage_state`` JSON (cookies + localStorage) under ``data/sessions/``
(gitignored). The browser fetcher injects it so crawls run "logged in". Sessions are
captured interactively via ``chubb-ci login <platform>`` (QR scan on the user's machine).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

# Domain substring → platform key. First match wins.
_PLATFORMS: list[tuple[str, str]] = [
    ("jd.com", "jd"),
    ("tmall.com", "taobao"),
    ("taobao.com", "taobao"),
    ("suning.com", "suning"),
    ("pinduoduo.com", "pdd"),
    ("douyin.com", "douyin"),
]

# Where to land the interactive login browser per platform.
LOGIN_URLS: dict[str, str] = {
    "jd": "https://passport.jd.com/new/login.aspx",
    "taobao": "https://login.taobao.com/",
    "suning": "https://passport.suning.com/ids/login",
    "pdd": "https://mobile.yangkeduo.com/login.html",
    "douyin": "https://www.douyin.com/",
}


def platform_for_url(url: str) -> str | None:
    """Return the platform key for a URL's host, or None if unknown."""
    host = (urlparse(url).netloc or "").lower()
    for needle, platform in _PLATFORMS:
        if needle in host:
            return platform
    return None


def sessions_dir(settings=None) -> Path:
    from chubb_ci.config.settings import get_settings

    d = (settings or get_settings()).data_path / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_path(platform: str, settings=None) -> Path:
    return sessions_dir(settings) / f"{platform}.json"


def load_state_for(url: str, settings=None) -> str | None:
    """Path to the saved storage_state for this URL's platform, if it exists."""
    platform = platform_for_url(url)
    if not platform:
        return None
    path = session_path(platform, settings)
    return str(path) if path.exists() else None


def known_platforms() -> list[str]:
    return sorted(LOGIN_URLS)
