"""FakeLLM — deterministic client for offline demos and unit tests.

Never makes a network call. Supply ``responses`` (a queue of raw string outputs) to
script multi-step behavior (e.g. an invalid JSON followed by a valid repair), or a
``handler`` callable for dynamic responses.
"""

from __future__ import annotations

from collections.abc import Callable

from chubb_ci.llm.base import LLMResponse


class FakeLLM:
    def __init__(
        self,
        responses: list[str] | None = None,
        handler: Callable[[str, str, bool], str] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._handler = handler
        self.calls: list[dict] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "model": model, "json_mode": json_mode})
        if self._handler is not None:
            content = self._handler(system, user, json_mode)
        elif self._responses:
            content = self._responses.pop(0)
        else:
            content = '{"products": []}'
        return LLMResponse(
            content=content,
            model=model or "fake",
            tokens_in=max(1, len(user) // 4),
            tokens_out=max(1, len(content) // 4),
        )
