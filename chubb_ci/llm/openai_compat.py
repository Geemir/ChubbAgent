"""OpenAI-compatible client — covers DeepSeek, GLM (Zhipu), Qwen, and OpenAI.

All four expose the same ``/chat/completions`` shape, so a single adapter + a base
URL swap is enough. Retries use exponential backoff via tenacity.
"""

from __future__ import annotations

from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from chubb_ci.llm.base import LLMError, LLMResponse


class OpenAICompatClient:
    """Chat-completions client for any OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: int = 60,
        max_retries: int = 3,
        supports_json_mode: bool = True,
    ) -> None:
        # Imported lazily so the package imports even if `openai` isn't installed.
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment guard
            raise LLMError("openai package not installed; run `uv sync`") from exc

        if not api_key:
            logger.warning("LLM api_key is empty; live calls will fail (offline/tests OK).")

        self._client = OpenAI(api_key=api_key or "missing", base_url=base_url, timeout=timeout)
        self._max_retries = max_retries
        self._supports_json_mode = supports_json_mode

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> LLMResponse:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type(Exception),
        )
        def _call() -> LLMResponse:
            kwargs: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
            }
            if json_mode and self._supports_json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            resp = self._client.chat.completions.create(**kwargs)
            choice = resp.choices[0].message.content or ""
            usage = resp.usage
            return LLMResponse(
                content=choice,
                model=model,
                tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            )

        try:
            return _call()
        except Exception as exc:  # noqa: BLE001 - normalize all provider errors
            raise LLMError(f"LLM call failed for model={model}: {exc}") from exc
