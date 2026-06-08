from __future__ import annotations

import json

import pytest

from note_generator.config import load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "LLM_PROVIDER",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "THREADS_LLM_CLASSIFIER_MODEL",
        "THREADS_LLM_TITLE_MODEL",
        "THREADS_LLM_OCR_MODEL",
        "THREADSIEVE_CONFIG",
        "CLASSIFIER_MODEL",
        "THREADS_GEMINI_TITLE_MODEL",
        "IMAGE_OCR_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_json(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_default_provider_is_gemini(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"], "llm": {}})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    cfg = load_config(dotenv_path=None)

    assert cfg.llm_provider == "gemini"
    assert cfg.llm_api_keys["gemini"] == "g"
    assert cfg.model_for_classification == "gemini-2.5-flash"


def test_provider_overridden_by_env(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"], "llm": {"provider": "gemini"}})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")

    cfg = load_config(dotenv_path=None)

    assert cfg.llm_provider == "anthropic"
    assert cfg.llm_api_keys["anthropic"] == "a"
    assert cfg.model_for_classification == "claude-sonnet-4-6"


def test_openai_defaults(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"], "llm": {"provider": "openai"}})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "o")

    cfg = load_config(dotenv_path=None)

    assert cfg.llm_provider == "openai"
    assert cfg.model_for_classification == "gpt-4o-mini"
    assert cfg.model_for_ocr == "gpt-4o"


def test_model_overrides_via_config_json(monkeypatch, tmp_path):
    path = _write_json(
        tmp_path,
        {
            "categories": ["AI"],
            "llm": {
                "provider": "anthropic",
                "text-model": "claude-opus-4-7",
                "title-model": "claude-sonnet-4-6",
                "vision-model": "claude-sonnet-4-6",
            },
        },
    )
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")

    cfg = load_config(dotenv_path=None)

    assert cfg.model_for_classification == "claude-opus-4-7"
    assert cfg.model_for_title == "claude-sonnet-4-6"
    assert cfg.model_for_ocr == "claude-sonnet-4-6"


def test_legacy_classifier_model_env_var(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"]})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("CLASSIFIER_MODEL", "gemini-2.5-pro-legacy")

    cfg = load_config(dotenv_path=None)

    assert cfg.model_for_classification == "gemini-2.5-pro-legacy"


def test_legacy_title_model_env_var(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"]})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("THREADS_GEMINI_TITLE_MODEL", "legacy-title-model")

    cfg = load_config(dotenv_path=None)

    assert cfg.model_for_title == "legacy-title-model"


def test_legacy_ocr_model_env_var(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"]})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))
    monkeypatch.setenv("IMAGE_OCR_MODEL", "legacy-ocr-model")

    cfg = load_config(dotenv_path=None)

    assert cfg.model_for_ocr == "legacy-ocr-model"


def test_llm_block_null_in_json(monkeypatch, tmp_path):
    path = _write_json(tmp_path, {"categories": ["AI"], "llm": None})
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(path))

    cfg = load_config(dotenv_path=None)

    assert cfg.llm_provider == "gemini"
    assert cfg.model_for_classification == "gemini-2.5-flash"
