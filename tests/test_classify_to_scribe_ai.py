from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import classify_to_scribe_ai as mod  # noqa: E402


SAMPLE_POSTS = [
    {"postId": "p_ai", "postUrl": "https://t.example/p_ai", "authorHandle": "@a", "contentText": "AI agent stuff"},
    {"postId": "p_tech", "postUrl": "https://t.example/p_tech", "authorHandle": "@b", "contentText": "new GPU release"},
    {"postId": "p_food", "postUrl": "https://t.example/p_food", "authorHandle": "@c", "contentText": "delicious ramen"},
]

ALL_CATEGORIES = ["AI", "科技", "Claude Code", "美食", "好笑的", "LingOrm", "職場", "心理健康"]


def make_config(unsaved_categories: set[str] | None = None) -> mod.ClassifyConfig:
    return mod.ClassifyConfig(
        categories=ALL_CATEGORIES,
        unsaved_categories=unsaved_categories if unsaved_categories is not None else {"AI", "科技"},
        hints=[],
    )


def make_client(category_by_post_id: dict[str, str]) -> MagicMock:
    """Mock GeminiClient that returns canned categories keyed by content snippet."""
    client = MagicMock()

    def fake_generate(prompt: str, *, model: str) -> str:
        for post_id, category in category_by_post_id.items():
            content = next(p["contentText"] for p in SAMPLE_POSTS if p["postId"] == post_id)
            if content in prompt:
                return category
        return ""

    client.generate_text.side_effect = fake_generate
    return client


def test_decision_filter_keeps_only_ai_and_tech():
    config = make_config({"AI", "科技"})
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="m", config=config)
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json", model="m", posts=SAMPLE_POSTS, classified=classified, config=config,
    )

    item_ids = [item["postId"] for item in payload["items"]]
    assert item_ids == ["p_ai", "p_tech"]
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["ai"] == 2
    assert payload["summary"]["not_ai"] == 1


def test_output_item_schema_fields_present():
    config = make_config({"AI", "科技"})
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="gemini-test", config=config)
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json", model="gemini-test", posts=SAMPLE_POSTS, classified=classified, config=config,
    )
    required_fields = {"postId", "postUrl", "decision", "confidence", "reason", "model", "classifiedAt"}
    for item in payload["items"]:
        assert required_fields <= set(item.keys())
        assert item["decision"] == "ai"
        assert item["confidence"] == 1.0
        assert item["reason"] in {"AI", "科技"}


def test_invalid_category_falls_into_unsure_failed_buckets():
    config = make_config()
    client = MagicMock()
    client.generate_text.return_value = "not-a-known-category"
    classified = [
        mod.classify_post(post=p, client=client, model="m", config=config)
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json", model="m", posts=SAMPLE_POSTS, classified=classified, config=config,
    )
    assert payload["summary"]["ai"] == 0
    assert payload["summary"]["unsure"] == 3
    assert payload["summary"]["failed"] == 0
    assert payload["items"] == []


def test_classifier_exception_marks_failed():
    config = make_config()
    client = MagicMock()
    client.generate_text.side_effect = RuntimeError("boom")
    classified = [
        mod.classify_post(post=p, client=client, model="m", config=config)
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json", model="m", posts=SAMPLE_POSTS, classified=classified, config=config,
    )
    assert payload["summary"]["ai"] == 0
    assert payload["summary"]["unsure"] == 3
    assert payload["summary"]["failed"] == 3
    assert payload["items"] == []


def test_custom_unsaved_categories():
    config = make_config({"美食"})
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="m", config=config)
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json", model="m", posts=SAMPLE_POSTS, classified=classified, config=config,
    )
    item_ids = [item["postId"] for item in payload["items"]]
    assert item_ids == ["p_food"]


def test_normalize_category_strips_wrappers_and_prefix():
    config = make_config()
    assert mod.normalize_category("分類: AI", config) == "AI"
    assert mod.normalize_category("「科技」", config) == "科技"
    assert mod.normalize_category("category：Claude Code\n", config) == "Claude Code"
    assert mod.normalize_category("", config) == ""


def test_load_config(tmp_path):
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(
        json.dumps({
            "categories": ["AI", "美食"],
            "unsaved-categories": ["AI"],
            "hints": ["some hint"],
        }),
        encoding="utf-8",
    )
    config = mod.load_config(cfg_file)
    assert config.categories == ["AI", "美食"]
    assert config.unsaved_categories == {"AI"}
    assert config.hints == ["some hint"]
    assert config.category_set == {"AI", "美食"}
    assert config.canonical_by_casefold == {"ai": "AI", "美食": "美食"}


def test_load_posts_rejects_non_array(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_posts(bad)
