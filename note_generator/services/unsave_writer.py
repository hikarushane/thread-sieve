from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from note_generator.models import ClassifiedBookmark


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_unsave_payload(
    *,
    source_file: str,
    model: str,
    total_count: int,
    classified: list[ClassifiedBookmark],
    unsaved_categories: set[str],
    failed_count: int = 0,
) -> dict:
    items_out = []
    unsave_count = 0
    keep_count = 0

    for item in classified:
        if item.category in unsaved_categories:
            unsave_count += 1
            items_out.append(
                {
                    "postId": _post_id(item),
                    "decision": "ai",
                    "confidence": 1.0,
                    "reason": item.category,
                    "postUrl": item.enriched.source.post_url,
                    "model": model,
                    "classifiedAt": timestamp(),
                }
            )
        else:
            keep_count += 1

    unsure_count = max(0, total_count - len(classified))
    return {
        "sourceFile": source_file,
        "generatedAt": timestamp(),
        "backend": f"threads-sieve/category_classifier ({model})",
        "unsavedCategories": sorted(unsaved_categories),
        "summary": {
            "total": total_count,
            "unsave": unsave_count,
            "keep": keep_count,
            "unsure": unsure_count,
            "failed": failed_count,
        },
        "items": items_out,
    }


def write_unsave_payload(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, output_path)


def _post_id(item: ClassifiedBookmark) -> str:
    value = item.enriched.source.metadata.get("postId")
    return str(value).strip() if value else item.enriched.source.post_url
