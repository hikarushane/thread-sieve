from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.infrastructure.gemini_client import GeminiClient
from note_generator.services.category_overrides import (
    CategoryOverride,
    detect_forced_category,
    parse_category_overrides,
)
from note_generator.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_INPUT_PATH,
    DEFAULT_UNSAVE_PATH,
    load_json_config,
    read_path_setting,
    resolve_json_config_path,
)


_CATEGORY_PREFIX_RE = re.compile(r"^(?:分類|category)\s*[:：]\s*", re.IGNORECASE)
_LEADING_WRAP_RE = re.compile(r'^[\s`"\'「『（(\[]+')
_TRAILING_WRAP_RE = re.compile(r'[\s`"\'」』）)\]]+$')

DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass
class ClassifyConfig:
    categories: list[str]
    unsaved_categories: set[str]
    hints: list[str]
    category_overrides: list[CategoryOverride] = field(default_factory=list)
    category_set: set[str] = field(init=False, repr=False)
    canonical_by_casefold: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.category_set = set(self.categories)
        self.canonical_by_casefold = {c.casefold(): c for c in self.categories}


@dataclass
class ClassifiedItem:
    post_id: str
    post_url: str
    decision: str
    confidence: float
    reason: str
    classified_at: str
    author_handle: str = ""
    author_name: str = ""
    content_text: str = ""


def parse_config(data: dict) -> ClassifyConfig:
    return ClassifyConfig(
        categories=data["categories"],
        unsaved_categories=set(data.get("unsaved-categories", [])),
        hints=data.get("hints", []),
        category_overrides=parse_category_overrides(data),
    )


def load_config(path: Path) -> ClassifyConfig:
    return parse_config(load_json_config(path))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def load_posts(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a top-level JSON array")
    return payload


def build_prompt(author_handle: str, content_text: str, config: ClassifyConfig) -> str:
    hints_block = "\n".join(f"- {h}" for h in config.hints)
    return (
        "請從以下分類中只選一個最適合的分類。\n"
        "只能輸出分類名稱本身，不要解釋、不要標點、不要額外文字。\n\n"
        f"可選分類：{'、'.join(config.categories)}\n\n"
        + (f"分類判別補充：\n{hints_block}\n\n" if hints_block else "")
        + f"作者：{author_handle}\n"
        f"內容：{content_text[:5000]}"
    )


def normalize_category(raw_category: str, config: ClassifyConfig) -> str:
    for line in raw_category.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        without_prefix = _CATEGORY_PREFIX_RE.sub("", candidate)
        normalized = _LEADING_WRAP_RE.sub("", without_prefix)
        normalized = _TRAILING_WRAP_RE.sub("", normalized)
        normalized = normalized.strip().rstrip("，。；：:,.!！?")
        if normalized:
            return config.canonical_by_casefold.get(normalized.casefold(), normalized)
    return ""


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_post(
    *,
    post: dict,
    client: GeminiClient,
    model: str,
    config: ClassifyConfig,
) -> tuple[ClassifiedItem, str]:
    """Returns (item, category). category may be empty string on failure."""
    author = post.get("authorHandle", "") or ""
    content = post.get("contentText", "") or ""
    post_id = post.get("postId", "") or ""
    post_url = post.get("postUrl", "") or ""

    forced_category = detect_forced_category(content, config.category_overrides, config.categories)
    if forced_category:
        decision = "ai" if forced_category in config.unsaved_categories else "not_ai"
        return (
            ClassifiedItem(
                post_id=post_id,
                post_url=post_url,
                decision=decision,
                confidence=1.0,
                reason=forced_category,
                classified_at=timestamp(),
            ),
            forced_category,
        )

    try:
        raw = client.generate_text(build_prompt(author, content, config), model=model)
    except Exception as error:
        return (
            ClassifiedItem(
                post_id=post_id,
                post_url=post_url,
                decision="unsure",
                confidence=0.0,
                reason=f"classifier error: {error}",
                classified_at=timestamp(),
                author_handle=author,
                author_name=str(post.get("authorName", "") or ""),
                content_text=content,
            ),
            "",
        )

    category = normalize_category(raw, config)
    if category not in config.category_set:
        return (
            ClassifiedItem(
                post_id=post_id,
                post_url=post_url,
                decision="unsure",
                confidence=0.0,
                reason=f"invalid category from Gemini: {raw[:200]!r}",
                classified_at=timestamp(),
                author_handle=author,
                author_name=str(post.get("authorName", "") or ""),
                content_text=content,
            ),
            "",
        )

    decision = "ai" if category in config.unsaved_categories else "not_ai"
    return (
        ClassifiedItem(
            post_id=post_id,
            post_url=post_url,
            decision=decision,
            confidence=1.0,
            reason=category,
            classified_at=timestamp(),
            author_handle=author,
            author_name=str(post.get("authorName", "") or ""),
            content_text=content,
        ),
        category,
    )


def build_output_payload(
    *,
    source_file: str,
    model: str,
    posts: list[dict],
    classified: list[tuple[ClassifiedItem, str]],
    config: ClassifyConfig,
) -> dict:
    posts_by_id = {
        str(post.get("postId") or ""): post
        for post in posts
        if isinstance(post, dict) and post.get("postId")
    }
    items_out = []
    ai_count = 0
    not_ai_count = 0
    unsure_count = 0
    failed_count = 0

    for item, category in classified:
        if item.decision == "ai":
            ai_count += 1
            post = posts_by_id.get(item.post_id, {})
            items_out.append(
                {
                    "postId": item.post_id,
                    "postUrl": item.post_url,
                    "authorHandle": item.author_handle or str(post.get("authorHandle", "") or ""),
                    "authorName": item.author_name or str(post.get("authorName", "") or ""),
                    "contentText": item.content_text or str(post.get("contentText", "") or ""),
                    "decision": item.decision,
                    "confidence": item.confidence,
                    "reason": item.reason,
                    "model": model,
                    "classifiedAt": item.classified_at,
                }
            )
        elif item.decision == "not_ai":
            not_ai_count += 1
        elif item.decision == "unsure":
            unsure_count += 1
            if "error" in item.reason.lower():
                failed_count += 1

    return {
        "sourceFile": source_file,
        "generatedAt": timestamp(),
        "backend": f"threads-sieve/category_classifier ({model})",
        "unsavedCategories": sorted(config.unsaved_categories),
        "summary": {
            "total": len(posts),
            "ai": ai_count,
            "not_ai": not_ai_count,
            "unsure": unsure_count,
            "failed": failed_count,
        },
        "items": items_out,
    }


def _pre_scan_env_file(argv: list[str]) -> str:
    for i, token in enumerate(argv):
        if token == "--env-file" and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith("--env-file="):
            return token.split("=", 1)[1]
    return ".env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify catch.json posts via Gemini, emit unsave.json")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--unsaved-categories", default=None, help="override config unsaved-categories (comma-separated)")
    parser.add_argument("--config", default=None, help=f"path to config.json (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def main() -> int:
    load_dotenv(Path(_pre_scan_env_file(sys.argv[1:])))
    args = parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key.strip():
        print("ERROR: GEMINI_API_KEY missing. Set in .env or pass --api-key.", file=sys.stderr)
        return 2

    config_path = resolve_json_config_path(args.config)
    if not config_path.exists():
        print(
            f"ERROR: config not found at {config_path}. "
            "Copy config.json, edit categories and hints, then retry.",
            file=sys.stderr,
        )
        return 2
    config_data = load_json_config(config_path)
    config = parse_config(config_data)

    if args.unsaved_categories and args.unsaved_categories.strip():
        config.unsaved_categories = {t.strip() for t in args.unsaved_categories.split(",") if t.strip()}

    input_path = Path(
        args.input
        or os.environ.get("CATCH_PATH")
        or read_path_setting(config_data, "catch-json", str(DEFAULT_INPUT_PATH))
    )
    output_path = Path(
        args.output
        or os.environ.get("UNSAVE_PATH")
        or read_path_setting(config_data, "unsave-json", str(DEFAULT_UNSAVE_PATH))
    )
    model = args.model or os.environ.get("CLASSIFIER_MODEL", DEFAULT_MODEL)

    posts = load_posts(input_path)
    client = GeminiClient(api_key=api_key)

    classified: list[tuple[ClassifiedItem, str]] = []
    for index, post in enumerate(posts, start=1):
        print(f"[{index}/{len(posts)}] classifying {post.get('postId', '?')}", file=sys.stderr)
        classified.append(classify_post(post=post, client=client, model=model, config=config))

    payload = build_output_payload(
        source_file=input_path.name,
        model=model,
        posts=posts,
        classified=classified,
        config=config,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, output_path)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
