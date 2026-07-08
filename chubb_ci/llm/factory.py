"""Build an :class:`LLMClient` from settings, and resolve per-tier model names."""

from __future__ import annotations

from loguru import logger

from chubb_ci.config.settings import Settings
from chubb_ci.llm.base import LLMClient
from chubb_ci.llm.providers import PROVIDER_PRESETS, get_preset

_TIERS = ("extract", "daily", "weekly")


def build_llm(settings: Settings, provider: str | None = None) -> LLMClient:
    """Construct the configured LLM client.

    ``provider="fake"`` returns a :class:`~chubb_ci.llm.fake.FakeLLM` (offline).
    ``provider="anthropic"`` uses the Claude SDK. Everything else uses the shared
    OpenAI-compatible client with the provider's base URL.
    """
    provider = (provider or settings.llm_provider).strip().lower()
    logger.debug("Building LLM client for provider={}", provider)

    if provider == "fake":
        from chubb_ci.llm.fake import FakeLLM

        return FakeLLM()

    if provider == "anthropic":
        from chubb_ci.llm.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    from chubb_ci.llm.openai_compat import OpenAICompatClient

    preset = get_preset(provider)
    return OpenAICompatClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or preset.base_url,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        supports_json_mode=preset.supports_json_mode,
    )


def resolve_model(settings: Settings, tier: str) -> str:
    """Return the model name for a tier (``extract`` | ``daily`` | ``weekly``).

    An explicit ``CHUBB_LLM_*_MODEL`` override wins; otherwise the provider preset
    default is used.
    """
    if tier not in _TIERS:
        raise ValueError(f"unknown model tier '{tier}'")
    override = {
        "extract": settings.llm_extract_model,
        "daily": settings.llm_daily_model,
        "weekly": settings.llm_weekly_model,
    }[tier]
    if override:
        return override
    provider = settings.llm_provider.strip().lower()
    if provider in PROVIDER_PRESETS:
        return getattr(get_preset(provider), f"{tier}_model")
    if provider == "fake":
        return "fake"
    raise ValueError(f"no model configured for provider '{provider}' tier '{tier}'")
