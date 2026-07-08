"""LLM client protocol and shared value objects."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class LLMError(RuntimeError):
    """Raised when an LLM call fails after retries."""


class LLMResponse(BaseModel):
    """Normalized result of a completion, independent of the provider SDK."""

    content: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


@runtime_checkable
class LLMClient(Protocol):
    """Minimal completion interface every provider adapter implements."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Return a completion for the given system/user prompts.

        Implementations must raise :class:`LLMError` on unrecoverable failure and
        should honor ``json_mode`` by requesting a JSON object when supported.
        """
        ...
