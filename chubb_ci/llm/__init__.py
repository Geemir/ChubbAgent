"""Provider-agnostic LLM layer.

Swapping providers (DeepSeek ↔ GLM ↔ Qwen ↔ OpenAI ↔ Claude) is a config change:
every client implements the same :class:`LLMClient` protocol.
"""

from chubb_ci.llm.base import LLMClient, LLMError, LLMResponse
from chubb_ci.llm.factory import build_llm
from chubb_ci.llm.fake import FakeLLM

__all__ = ["LLMClient", "LLMError", "LLMResponse", "build_llm", "FakeLLM"]
