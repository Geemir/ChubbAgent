"""Fetcher protocol and the normalized fetch result."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class FetchResult(BaseModel):
    """Outcome of fetching one URL, uniform across fetcher backends."""

    url: str
    ok: bool
    status: int = 0
    html: str | None = None
    blocked: bool = False  # anti-bot / captcha / login wall detected
    error: str | None = None


@runtime_checkable
class Fetcher(Protocol):
    """Fetches a single URL and returns a :class:`FetchResult` (never raises)."""

    def fetch(self, url: str) -> FetchResult: ...
