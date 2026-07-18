from __future__ import annotations

from typing import Mapping

from note_generator.infrastructure.anthropic_client import AnthropicClient
from note_generator.infrastructure.claude_code_cli_client import ClaudeCodeCLIClient
from note_generator.infrastructure.codex_cli_client import CodexCLIClient
from note_generator.infrastructure.gemini_client import GeminiClient
from note_generator.infrastructure.openai_client import OpenAIClient
from note_generator.services.llm_client import LLMClient


SUPPORTED_PROVIDERS = ("gemini", "anthropic", "openai", "claude-code", "codex")


def build_llm_client(provider: str, api_keys: Mapping[str, str]) -> LLMClient:
    """Return the LLMClient implementation for `provider`.

    `api_keys` maps provider name → API key. Missing/empty keys raise RuntimeError
    inside the adapter constructor. CLI providers (claude-code, codex) ignore
    `api_keys` and use the local CLI's own login session.
    """
    normalized = (provider or "").strip().lower()
    if normalized == "gemini":
        return GeminiClient(api_key=api_keys.get("gemini", ""))
    if normalized == "anthropic":
        return AnthropicClient(api_key=api_keys.get("anthropic", ""))
    if normalized == "openai":
        return OpenAIClient(api_key=api_keys.get("openai", ""))
    if normalized == "claude-code":
        return ClaudeCodeCLIClient()
    if normalized == "codex":
        return CodexCLIClient()
    raise ValueError(
        f"unsupported llm provider: {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )
