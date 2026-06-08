from __future__ import annotations

import pytest

from note_generator.infrastructure.anthropic_client import AnthropicClient
from note_generator.infrastructure.gemini_client import GeminiClient
from note_generator.infrastructure.llm_factory import build_llm_client
from note_generator.infrastructure.openai_client import OpenAIClient


def test_factory_returns_gemini_for_gemini_provider(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.gemini_client.genai.Client", lambda **_: object())
    client = build_llm_client("gemini", {"gemini": "key"})
    assert isinstance(client, GeminiClient)


def test_factory_returns_anthropic_for_anthropic_provider(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.anthropic_client.Anthropic", lambda **_: object())
    client = build_llm_client("anthropic", {"anthropic": "key"})
    assert isinstance(client, AnthropicClient)


def test_factory_returns_openai_for_openai_provider(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.openai_client.OpenAI", lambda **_: object())
    client = build_llm_client("openai", {"openai": "key"})
    assert isinstance(client, OpenAIClient)


def test_factory_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="unsupported llm provider"):
        build_llm_client("ollama", {})


def test_factory_raises_when_required_key_missing(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.anthropic_client.Anthropic", lambda **_: object())
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_llm_client("anthropic", {"anthropic": ""})
