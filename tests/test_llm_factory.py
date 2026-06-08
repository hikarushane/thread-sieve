from __future__ import annotations

import pytest

from note_generator.infrastructure.anthropic_client import AnthropicClient
from note_generator.infrastructure.gemini_client import GeminiClient
from note_generator.infrastructure.llm_factory import build_llm_client
from note_generator.infrastructure.openai_client import OpenAIClient


def _spy(captured):
    def factory(**kwargs):
        captured.append(kwargs)
        return object()
    return factory


def test_factory_returns_gemini_and_forwards_key(monkeypatch):
    captured = []
    monkeypatch.setattr("note_generator.infrastructure.gemini_client.genai.Client", _spy(captured))
    client = build_llm_client("gemini", {"gemini": "g-key"})
    assert isinstance(client, GeminiClient)
    assert captured == [{"api_key": "g-key"}]


def test_factory_returns_anthropic_and_forwards_key(monkeypatch):
    captured = []
    monkeypatch.setattr("note_generator.infrastructure.anthropic_client.Anthropic", _spy(captured))
    client = build_llm_client("anthropic", {"anthropic": "a-key"})
    assert isinstance(client, AnthropicClient)
    assert captured == [{"api_key": "a-key"}]


def test_factory_returns_openai_and_forwards_key(monkeypatch):
    captured = []
    monkeypatch.setattr("note_generator.infrastructure.openai_client.OpenAI", _spy(captured))
    client = build_llm_client("openai", {"openai": "o-key"})
    assert isinstance(client, OpenAIClient)
    assert captured == [{"api_key": "o-key"}]


def test_factory_raises_for_unknown_provider():
    with pytest.raises(ValueError, match="unsupported llm provider"):
        build_llm_client("ollama", {})


def test_factory_raises_when_gemini_key_missing(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.gemini_client.genai.Client", lambda **_: object())
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_llm_client("gemini", {"gemini": ""})


def test_factory_raises_when_anthropic_key_missing(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.anthropic_client.Anthropic", lambda **_: object())
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_llm_client("anthropic", {"anthropic": ""})


def test_factory_raises_when_openai_key_missing(monkeypatch):
    monkeypatch.setattr("note_generator.infrastructure.openai_client.OpenAI", lambda **_: object())
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_llm_client("openai", {"openai": ""})


@pytest.mark.parametrize("name", ["Gemini", "GEMINI", " gemini ", " Gemini\t"])
def test_factory_normalizes_provider_name(monkeypatch, name):
    monkeypatch.setattr("note_generator.infrastructure.gemini_client.genai.Client", lambda **_: object())
    assert isinstance(build_llm_client(name, {"gemini": "k"}), GeminiClient)
