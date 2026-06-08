from __future__ import annotations

from typing import Mapping

from note_generator.infrastructure.anthropic_client import AnthropicClient
from note_generator.infrastructure.gemini_client import GeminiClient
from note_generator.infrastructure.openai_client import OpenAIClient
from note_generator.services.llm_client import LLMClient


SUPPORTED_PROVIDERS = ("gemini", "anthropic", "openai")


def build_llm_client(provider: str, api_keys: Mapping[str, str]) -> LLMClient:
    """Return the LLMClient implementation for `provider`.

    `api_keys` maps provider name → API key. Missing/empty keys raise RuntimeError
    inside the adapter constructor.
    """
    normalized = (provider or "").strip().lower()
    if normalized == "gemini":
        return GeminiClient(api_key=api_keys.get("gemini", ""))
    if normalized == "anthropic":
        return AnthropicClient(api_key=api_keys.get("anthropic", ""))
    if normalized == "openai":
        return OpenAIClient(api_key=api_keys.get("openai", ""))
    raise ValueError(
        f"unsupported llm provider: {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
