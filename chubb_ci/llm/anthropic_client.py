"""Anthropic (Claude) adapter — demonstrates provider-swappability.

Claude uses a different SDK/shape than the OpenAI-compatible providers, yet it
implements the exact same :class:`~chubb_ci.llm.base.LLMClient` protocol, so switching
to it is ``CHUBB_LLM_PROVIDER=anthropic`` plus a key — no change to callers.

Requires the optional dependency: ``uv sync --extra anthropic``.
"""

from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential

from chubb_ci.llm.base import LLMError, LLMResponse


class AnthropicClient:
    def __init__(self, *, api_key: str, timeout: int = 60, max_retries: int = 3) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dep
            raise LLMError("anthropic not installed; run `uv sync --extra anthropic`") from exc
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._max_retries = max_retries

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # Claude has no json_object flag; prefilling "{" strongly biases JSON output.
        messages = [{"role": "user", "content": user}]
        if json_mode:
            messages.append({"role": "assistant", "content": "{"})

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
        )
        def _call() -> LLMResponse:
            resp = self._client.messages.create(
                model=model,
                system=system,
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            if json_mode and not text.lstrip().startswith("{"):
                text = "{" + text
            return LLMResponse(
                content=text,
                model=model,
                tokens_in=resp.usage.input_tokens,
                tokens_out=resp.usage.output_tokens,
            )

        try:
            return _call()
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic call failed for model={model}: {exc}") from exc
