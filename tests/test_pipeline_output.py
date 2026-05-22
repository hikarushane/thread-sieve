"""Integration test: verify classify pipeline output for the 2026-05-10 cutoff run.

Run AFTER the pipeline completes:
    python scripts/classify_to_scribe_ai.py --output test-output/unsave.json

Anchor posts (from the 2026-05-10 scrape window):
  DYoil5PFB0c  — latest post, category AI / 科技 / Claude Code
  DYJRyUFDJP7  — oldest post at cutoff 2026-05-10, category 職場
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "test-output" / "unsave.json"

UNSAVED_CATEGORIES = {"AI", "科技", "Claude Code", "職場", "美食", "身體健康", "心理健康"}


@pytest.fixture(scope="module")
def output() -> dict:
    if not OUTPUT_PATH.exists():
        pytest.fail(
            f"Pipeline output not found: {OUTPUT_PATH}\n"
            "Run the pipeline first:\n"
            "  python scripts/agent_driver.py scrape --cutoff 2026-05-10 --wait-seconds 300\n"
            "  python scripts/classify_to_scribe_ai.py --output test-output/unsave.json"
        )
    return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))


def test_anchor_posts_present_in_output(output: dict) -> None:
    item_ids = {item["postId"] for item in output["items"]}
    assert "DYoil5PFB0c" in item_ids, "latest anchor post DYoil5PFB0c missing from output"
    assert "DYJRyUFDJP7" in item_ids, "cutoff anchor post DYJRyUFDJP7 missing from output"


def test_latest_anchor_classified_as_ai_or_tech_or_claudecode(output: dict) -> None:
    items_by_id = {item["postId"]: item for item in output["items"]}
    item = items_by_id.get("DYoil5PFB0c")
    assert item is not None, "DYoil5PFB0c not in items"
    assert item["reason"] in {"AI", "科技", "Claude Code"}, (
        f"DYoil5PFB0c: expected reason in {{AI, 科技, Claude Code}}, got {item['reason']!r}"
    )


def test_cutoff_anchor_classified_as_workplace(output: dict) -> None:
    items_by_id = {item["postId"]: item for item in output["items"]}
    item = items_by_id.get("DYJRyUFDJP7")
    assert item is not None, "DYJRyUFDJP7 not in items"
    assert item["reason"] == "職場", (
        f"DYJRyUFDJP7: expected reason='職場', got {item['reason']!r}"
    )


def test_all_output_items_have_ai_decision(output: dict) -> None:
    non_ai = [item for item in output["items"] if item["decision"] != "ai"]
    assert not non_ai, (
        f"{len(non_ai)} item(s) in output with decision != 'ai': "
        + ", ".join(f"{i['postId']}={i['decision']!r}" for i in non_ai[:5])
    )


def test_output_item_reasons_are_unsaved_categories(output: dict) -> None:
    bad = [item for item in output["items"] if item["reason"] not in UNSAVED_CATEGORIES]
    assert not bad, (
        f"Items with reason outside unsaved-categories: "
        + ", ".join(f"{i['postId']}={i['reason']!r}" for i in bad[:5])
    )
