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


def make_client(category_by_post_id: dict[str, str]) -> MagicMock:
    """Mock GeminiClient that returns canned categories keyed by content snippet."""
    client = MagicMock()

    def fake_generate(prompt: str, *, model: str) -> str:
        for post_id, category in category_by_post_id.items():
            # The prompt embeds the contentText from SAMPLE_POSTS.
            content = next(p["contentText"] for p in SAMPLE_POSTS if p["postId"] == post_id)
            if content in prompt:
                return category
        return ""

    client.generate_text.side_effect = fake_generate
    return client


def test_decision_filter_keeps_only_ai_and_tech():
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="m", ai_categories={"AI", "科技"})
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json",
        model="m",
        posts=SAMPLE_POSTS,
        classified=classified,
        ai_categories={"AI", "科技"},
    )

    item_ids = [item["postId"] for item in payload["items"]]
    assert item_ids == ["p_ai", "p_tech"]
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["ai"] == 2
    assert payload["summary"]["not_ai"] == 1


def test_output_item_schema_fields_present():
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="gemini-test", ai_categories={"AI", "科技"})
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json",
        model="gemini-test",
        posts=SAMPLE_POSTS,
        classified=classified,
        ai_categories={"AI", "科技"},
    )
    required_fields = {"postId", "postUrl", "decision", "confidence", "reason", "model", "classifiedAt"}
    for item in payload["items"]:
        assert required_fields <= set(item.keys())
        assert item["decision"] == "ai"
        assert item["confidence"] == 1.0
        assert item["reason"] in {"AI", "科技"}


def test_invalid_category_falls_into_unsure_failed_buckets():
    client = MagicMock()
    client.generate_text.return_value = "not-a-known-category"
    classified = [
        mod.classify_post(post=p, client=client, model="m", ai_categories={"AI", "科技"})
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json",
        model="m",
        posts=SAMPLE_POSTS,
        classified=classified,
        ai_categories={"AI", "科技"},
    )
    assert payload["summary"]["ai"] == 0
    assert payload["summary"]["unsure"] == 3
    assert payload["summary"]["failed"] == 0
    assert payload["items"] == []


def test_classifier_exception_marks_failed():
    client = MagicMock()
    client.generate_text.side_effect = RuntimeError("boom")
    classified = [
        mod.classify_post(post=p, client=client, model="m", ai_categories={"AI", "科技"})
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json",
        model="m",
        posts=SAMPLE_POSTS,
        classified=classified,
        ai_categories={"AI", "科技"},
    )
    assert payload["summary"]["ai"] == 0
    assert payload["summary"]["unsure"] == 3
    assert payload["summary"]["failed"] == 3
    assert payload["items"] == []


def test_custom_ai_categories():
    client = make_client({"p_ai": "AI", "p_tech": "科技", "p_food": "美食"})
    classified = [
        mod.classify_post(post=p, client=client, model="m", ai_categories={"美食"})
        for p in SAMPLE_POSTS
    ]
    payload = mod.build_output_payload(
        source_file="scribe.json",
        model="m",
        posts=SAMPLE_POSTS,
        classified=classified,
        ai_categories={"美食"},
    )
    item_ids = [item["postId"] for item in payload["items"]]
    assert item_ids == ["p_food"]


def test_parse_ai_categories_handles_blank_and_default():
    assert mod.parse_ai_categories("") == set(mod.DEFAULT_AI_CATEGORIES)
    assert mod.parse_ai_categories("AI, 科技") == {"AI", "科技"}
    assert mod.parse_ai_categories("好笑的") == {"好笑的"}


def test_normalize_category_strips_wrappers_and_prefix():
    assert mod.normalize_category("分類: AI") == "AI"
    assert mod.normalize_category("「科技」") == "科技"
    assert mod.normalize_category("category：Claude Code\n") == "Claude Code"
    assert mod.normalize_category("") == ""


def test_load_posts_rejects_non_array(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_posts(bad)
