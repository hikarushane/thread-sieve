from __future__ import annotations

import json
from pathlib import Path

from note_generator.services.threads_reply_enricher import (
    PageSnapshot,
    extract_post_image_urls_from_image_records,
)


class SnapshotMissingError(RuntimeError):
    """Raised when snapshots.json has no usable entry for a URL."""


class SnapshotFileThreadPageClient:
    """ThreadPageClient backed by a snapshots.json produced by the desktop app.

    Format (spec §7): {"generatedAt": str, "items": {url: {bodyText, embeddedJsonBlobs,
    imageRecords, fetchedAt, error}}}. Raising on missing entries lets
    ThreadsReplyEnricher fall back to primary content exactly as it does when
    Playwright fails.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._items: dict[str, dict] = self._load(self._path)

    @staticmethod
    def _load(path: Path) -> dict[str, dict]:
        if not path.exists():
            raise SnapshotMissingError(f"--snapshots file not found: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SnapshotMissingError(f"--snapshots file could not be read: {path} ({exc})") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SnapshotMissingError(f"--snapshots file has invalid JSON: {path} ({exc})") from exc
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            raise SnapshotMissingError(f"--snapshots file is missing an 'items' object: {path}")
        return items

    def fetch_body_text(self, url: str) -> str:
        return self._entry(url).get("bodyText", "") or ""

    def fetch_image_urls(self, url: str) -> list[str]:
        records = self._entry(url).get("imageRecords") or []
        return extract_post_image_urls_from_image_records(list(records))

    def fetch_page_snapshot(self, url: str) -> PageSnapshot:
        entry = self._entry(url)
        blobs = entry.get("embeddedJsonBlobs") or []
        return PageSnapshot(
            body_text=entry.get("bodyText", "") or "",
            embedded_json_blobs=[str(blob) for blob in blobs],
        )

    def _entry(self, url: str) -> dict:
        entry = self._items.get(url)
        if not isinstance(entry, dict):
            raise SnapshotMissingError(f"no snapshot for {url}")
        error = entry.get("error")
        if error:
            raise SnapshotMissingError(f"snapshot for {url} failed: {error}")
        return entry
