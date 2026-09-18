from __future__ import annotations

import json
from pathlib import Path

import pytest

from note_generator.services.snapshot_file_client import (
    SnapshotFileThreadPageClient,
    SnapshotMissingError,
)

URL = "https://www.threads.com/@a/post/X1"


def _write(tmp_path: Path, items: dict) -> Path:
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps({"generatedAt": "2026-09-14T20:00:00Z", "items": items}), encoding="utf-8")
    return path


def _entry(**overrides) -> dict:
    base = {
        "bodyText": "body text here",
        "embeddedJsonBlobs": ['{"thread_items": []}'],
        "imageRecords": [],
        "fetchedAt": "2026-09-14T20:00:05Z",
        "error": None,
    }
    base.update(overrides)
    return base


def test_fetch_page_snapshot_returns_body_and_blobs(tmp_path: Path) -> None:
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry()}))
    snapshot = client.fetch_page_snapshot(URL)
    assert snapshot.body_text == "body text here"
    assert snapshot.embedded_json_blobs == ['{"thread_items": []}']


def test_fetch_body_text(tmp_path: Path) -> None:
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry()}))
    assert client.fetch_body_text(URL) == "body text here"


def test_missing_url_raises(tmp_path: Path) -> None:
    client = SnapshotFileThreadPageClient(_write(tmp_path, {}))
    with pytest.raises(SnapshotMissingError):
        client.fetch_page_snapshot(URL)


def test_entry_with_error_raises(tmp_path: Path) -> None:
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry(error="timeout")}))
    with pytest.raises(SnapshotMissingError, match="timeout"):
        client.fetch_page_snapshot(URL)


def test_fetch_image_urls_filters_records_like_playwright_client(tmp_path: Path) -> None:
    records = [
        {
            "src": "https://scontent.cdninstagram.com/v/t51.82787-15/big.jpg",
            "w": 1080,
            "h": 1350,
            "alt": "",
        },
        {"src": "https://scontent.cdninstagram.com/v/t51/avatar.jpg", "w": 40, "h": 40, "alt": "頭像"},
    ]
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry(imageRecords=records)}))
    from note_generator.services.threads_reply_enricher import extract_post_image_urls_from_image_records

    expected = ["https://scontent.cdninstagram.com/v/t51.82787-15/big.jpg"]
    assert client.fetch_image_urls(URL) == expected
    assert client.fetch_image_urls(URL) == extract_post_image_urls_from_image_records(records)


def test_constructor_reads_file_once_and_caches(tmp_path: Path) -> None:
    path = _write(tmp_path, {URL: _entry()})
    client = SnapshotFileThreadPageClient(path)
    path.write_text("{}", encoding="utf-8")
    assert client.fetch_body_text(URL) == "body text here"


def test_missing_file_raises_at_construction(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist.json"
    with pytest.raises(SnapshotMissingError, match="not found"):
        SnapshotFileThreadPageClient(path)


def test_invalid_json_raises_at_construction(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotMissingError, match="invalid JSON"):
        SnapshotFileThreadPageClient(path)


def test_missing_items_dict_raises_at_construction(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps({"generatedAt": "2026-09-14T20:00:00Z"}), encoding="utf-8")
    with pytest.raises(SnapshotMissingError, match="items"):
        SnapshotFileThreadPageClient(path)


def test_fetch_page_snapshot_returns_dom_thread(tmp_path: Path) -> None:
    dom_posts = [
        {
            "code": "FOCAL01",
            "authorHandle": "original_poster",
            "text": "母帖全文",
            "datetime": "2026-09-18T00:00:00.000Z",
            "role": "focal",
            "group": 0,
        }
    ]
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry(domThread=dom_posts)}))
    snapshot = client.fetch_page_snapshot(URL)
    assert snapshot.dom_thread == dom_posts


def test_fetch_page_snapshot_defaults_dom_thread_to_empty_list(tmp_path: Path) -> None:
    client = SnapshotFileThreadPageClient(_write(tmp_path, {URL: _entry()}))
    snapshot = client.fetch_page_snapshot(URL)
    assert snapshot.dom_thread == []
