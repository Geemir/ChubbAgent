"""Provider presets: default base URLs and model tiers per provider.

Model tiering: a cheap/fast model for the high-volume extraction hot path, a stronger
model for the low-volume weekly report. Override any value via ``.env``.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProviderPreset(BaseModel):
    base_url: str
    extract_model: str
    daily_model: str
    weekly_model: str
    #: Whether the OpenAI-compatible endpoint supports response_format=json_object.
    supports_json_mode: bool = True


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    # China-hosted, Chinese-native, cheapest reliable option; JSON mode + off-peak pricing.
    "deepseek": ProviderPreset(
        base_url="https://api.deepseek.com",
        extract_model="deepseek-chat",
        daily_model="deepseek-chat",
        weekly_model="deepseek-reasoner",
    ),
    # Zhipu GLM — strong Chinese business prose + native tool use (good for Phase 2).
    "glm": ProviderPreset(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        extract_model="glm-4-flash",
        daily_model="glm-4-flash",
        weekly_model="glm-4.6",
    ),
    # Alibaba Qwen (DashScope OpenAI-compatible mode).
    "qwen": ProviderPreset(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        extract_model="qwen-turbo",
        daily_model="qwen-turbo",
        weekly_model="qwen-max",
    ),
    "openai": ProviderPreset(
        base_url="https://api.openai.com/v1",
        extract_model="gpt-4o-mini",
        daily_model="gpt-4o-mini",
        weekly_model="gpt-4o",
    ),
    # Anthropic uses a different SDK (see anthropic_client.py); base_url unused.
    "anthropic": ProviderPreset(
        base_url="",
        extract_model="claude-haiku-4-5-20251001",
        daily_model="claude-haiku-4-5-20251001",
        weekly_model="claude-sonnet-5",
        supports_json_mode=False,
    ),
}


def get_preset(provider: str) -> ProviderPreset:
    key = provider.strip().lower()
    if key not in PROVIDER_PRESETS:
        raise ValueError(
            f"unknown provider '{provider}'. Known: {', '.join(PROVIDER_PRESETS)}"
        )
    return PROVIDER_PRESETS[key]
