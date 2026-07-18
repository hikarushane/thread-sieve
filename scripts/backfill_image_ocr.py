from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.config import resolve_json_config_path
from image_ocr_to_markdown import (
    DEFAULT_MODEL,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_OCR_BACKEND,
    DEFAULT_OCR_METHOD,
    DEFAULT_PROMPT_TYPE,
    build_ocr_image,
    fetch_image_urls_with_playwright,
    load_dotenv,
    read_config_bool,
    read_config_int,
    read_config_str,
    read_int_env,
    read_ocr_config,
)


DEFAULT_MIN_CONTENT_CHARS = 800
IMAGE_TEXT_HEADING = "## 圖片文字"
SOURCES_HEADING = "## Sources"
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_IMAGE_TEXT_SECTION_RE = re.compile(r"\n*## 圖片文字\r?\n\r?\n.*?(?=\r?\n## |\Z)", re.DOTALL)
_SOURCES_SECTION_RE = re.compile(r"\r?\n## Sources\r?\n.*\Z", re.DOTALL)
_QUOTED_RE = re.compile(r"\A(['\"])(.*)\1\Z")


@dataclass(frozen=True)
class BackfillDecision:
    status: str
    reason: str
    post_url: str | None = None
    chars_before: int = 0


def parse_frontmatter(markdown: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(markdown)
    if not match:
        return {}
    values: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        values[key.strip()] = _strip_quotes(raw_value.strip())
    return values


def _strip_quotes(value: str) -> str:
    match = _QUOTED_RE.match(value)
    if not match:
        return value
    return match.group(2)


def extract_frontmatter_url(markdown: str) -> str | None:
    frontmatter = parse_frontmatter(markdown)
    return frontmatter.get("網址") or frontmatter.get("url") or None


def has_image_text_section(markdown: str) -> bool:
    return IMAGE_TEXT_HEADING in markdown


def main_content_chars(markdown: str) -> int:
    text = _FRONTMATTER_RE.sub("", markdown, count=1)
    text = _IMAGE_TEXT_SECTION_RE.sub("", text)
    text = _SOURCES_SECTION_RE.sub("", text)
    return len("".join(text.split()))


def decide_note(markdown: str, *, min_content_chars: int = DEFAULT_MIN_CONTENT_CHARS, force: bool = False) -> BackfillDecision:
    frontmatter = parse_frontmatter(markdown)
    status = frontmatter.get("status", "")
    post_url = extract_frontmatter_url(markdown)
    chars_before = main_content_chars(markdown)

    if status != "stub":
        return BackfillDecision("skipped", "status_not_stub", post_url, chars_before)
    if not post_url:
        return BackfillDecision("skipped", "missing_url", None, chars_before)
    if has_image_text_section(markdown) and not force:
        return BackfillDecision("skipped", "already_has_image_text", post_url, chars_before)
    if chars_before >= min_content_chars:
        return BackfillDecision("skipped", "content_detailed_enough", post_url, chars_before)
    return BackfillDecision("candidate", "eligible", post_url, chars_before)


def build_image_text_section(ocr_texts: list[str]) -> str:
    parts = [IMAGE_TEXT_HEADING]
    for index, text in enumerate([text.strip() for text in ocr_texts if text.strip()], start=1):
        parts.append(f"### 圖片 {index}\n\n{text}")
    return "\n\n".join(parts) + "\n"


def insert_image_text_section(markdown: str, ocr_texts: list[str], *, force: bool = False) -> str:
    if not any(text.strip() for text in ocr_texts):
        return markdown

    section = build_image_text_section(ocr_texts)
    if has_image_text_section(markdown):
        if not force:
            return markdown
        text = _IMAGE_TEXT_SECTION_RE.sub("", markdown).rstrip()
    else:
        text = markdown.rstrip()

    sources_index = text.find(SOURCES_HEADING)
    if sources_index == -1:
        updated = text + "\n\n" + section
    else:
        updated = text[:sources_index].rstrip() + "\n\n" + section + "\n" + text[sources_index:]
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def iter_markdown_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".md" else []
    return sorted(path.rglob("*.md"))


def default_log_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data") / f"backfill-image-ocr-{stamp}.jsonl"


def write_event(log_path: Path, event: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def make_event(
    *,
    path: Path,
    decision: BackfillDecision,
    status: str,
    reason: str,
    dry_run: bool,
    image_count: int = 0,
    ocr_text_count: int = 0,
    chars_after: int | None = None,
    error: str | None = None,
) -> dict:
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "path": str(path),
        "post_url": decision.post_url,
        "status": status,
        "reason": reason,
        "dry_run": dry_run,
        "image_count": image_count,
        "ocr_text_count": ocr_text_count,
        "chars_before": decision.chars_before,
        "chars_after": chars_after if chars_after is not None else decision.chars_before,
        "error": error,
    }


def run_batch(
    *,
    path: Path,
    log_path: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    min_content_chars: int = DEFAULT_MIN_CONTENT_CHARS,
    limit: int | None = None,
    headless: bool = True,
    discover_images: Callable[..., list[str]] | None = None,
    ocr_image: Callable[[str], str] | None = None,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    ocr_backend: str = DEFAULT_OCR_BACKEND,
    ocr_method: str = DEFAULT_OCR_METHOD,
    prompt_type: str = DEFAULT_PROMPT_TYPE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    include_headers_footers: bool = False,
) -> dict[str, int | str]:
    if not path.exists():
        raise FileNotFoundError(path)

    log_path = log_path or default_log_path()
    files = iter_markdown_files(path)
    if limit is not None:
        files = files[:limit]

    summary = {"scanned": 0, "processed": 0, "skipped": 0, "no_images": 0, "failed": 0}
    image_discoverer = discover_images or fetch_image_urls_with_playwright
    image_ocr: Callable[[str], str] | None = ocr_image

    for markdown_path in files:
        decision: BackfillDecision | None = None
        failure_reason = "read_failed"
        summary["scanned"] += 1
        try:
            original = markdown_path.read_text(encoding="utf-8")
            decision = decide_note(original, min_content_chars=min_content_chars, force=force)
            if decision.status == "skipped":
                summary["skipped"] += 1
                write_event(
                    log_path,
                    make_event(
                        path=markdown_path,
                        decision=decision,
                        status="skipped",
                        reason=decision.reason,
                        dry_run=dry_run,
                    ),
                )
                continue

            if dry_run:
                summary["processed"] += 1
                write_event(
                    log_path,
                    make_event(
                        path=markdown_path,
                        decision=decision,
                        status="processed",
                        reason="dry_run_candidate",
                        dry_run=True,
                    ),
                )
                continue

            assert decision.post_url is not None
            failure_reason = "fetch_failed"
            image_urls = image_discoverer(decision.post_url, headless=headless)
            if not image_urls:
                summary["no_images"] += 1
                write_event(
                    log_path,
                    make_event(
                        path=markdown_path,
                        decision=decision,
                        status="no_images",
                        reason="no_images_found",
                        dry_run=False,
                    ),
                )
                continue

            if image_ocr is None:
                image_ocr = _build_default_ocr_image(
                    api_key=api_key,
                    model=model,
                    ocr_backend=ocr_backend,
                    ocr_method=ocr_method,
                    prompt_type=prompt_type,
                    max_output_tokens=max_output_tokens,
                    include_headers_footers=include_headers_footers,
                )
            failure_reason = "ocr_failed"
            ocr_texts = [image_ocr(image_url).strip() for image_url in image_urls]
            ocr_texts = [text for text in ocr_texts if text]
            if not ocr_texts:
                summary["failed"] += 1
                write_event(
                    log_path,
                    make_event(
                        path=markdown_path,
                        decision=decision,
                        status="failed",
                        reason="ocr_failed",
                        dry_run=False,
                        image_count=len(image_urls),
                    ),
                )
                continue

            updated = insert_image_text_section(original, ocr_texts, force=force)
            failure_reason = "write_failed"
            markdown_path.write_text(updated, encoding="utf-8")
            summary["processed"] += 1
            write_event(
                log_path,
                make_event(
                    path=markdown_path,
                    decision=decision,
                    status="processed",
                    reason="ocr_replaced" if has_image_text_section(original) else "ocr_inserted",
                    dry_run=False,
                    image_count=len(image_urls),
                    ocr_text_count=len(ocr_texts),
                    chars_after=main_content_chars(updated),
                ),
            )
        except Exception as error:
            summary["failed"] += 1
            if decision is None:
                decision = BackfillDecision("candidate", "unknown")
            write_event(
                log_path,
                make_event(
                    path=markdown_path,
                    decision=decision,
                    status="failed",
                    reason=failure_reason,
                    dry_run=dry_run,
                    error=str(error),
                ),
            )

    return {**summary, "log": str(log_path)}


def _build_default_ocr_image(
    *,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    ocr_backend: str = DEFAULT_OCR_BACKEND,
    ocr_method: str = DEFAULT_OCR_METHOD,
    prompt_type: str = DEFAULT_PROMPT_TYPE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    include_headers_footers: bool = False,
) -> Callable[[str], str]:
    return build_ocr_image(
        backend=ocr_backend,
        api_key=api_key,
        model=model,
        ocr_method=ocr_method,
        prompt_type=prompt_type,
        max_output_tokens=max_output_tokens,
        include_headers_footers=include_headers_footers,
    )


def print_summary(summary: dict[str, int | str]) -> None:
    print("Backfill Image OCR summary")
    print(f"Scanned: {summary['scanned']}")
    print(f"Processed: {summary['processed']}")
    print(f"Skipped: {summary['skipped']}")
    print(f"No images: {summary['no_images']}")
    print(f"Failed: {summary['failed']}")
    print(f"Log: {summary['log']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Threads image OCR into existing markdown notes.")
    parser.add_argument("--path", required=True)
    parser.add_argument("--log", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--min-content-chars", type=int, default=DEFAULT_MIN_CONTENT_CHARS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--ocr-backend", default="")
    parser.add_argument("--ocr-method", default="")
    parser.add_argument("--prompt-type", default="")
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--include-headers-footers", action="store_true")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(args.env_file))
    ocr_config = read_ocr_config(resolve_json_config_path(args.config))
    max_output_tokens = args.max_output_tokens
    if max_output_tokens is None:
        max_output_tokens = read_int_env(
            "IMAGE_OCR_MAX_OUTPUT_TOKENS",
            "MAX_OUTPUT_TOKENS",
            default=read_config_int(ocr_config, "max-output-tokens", DEFAULT_MAX_OUTPUT_TOKENS),
        )
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    model = args.model or os.environ.get("IMAGE_OCR_MODEL", DEFAULT_MODEL)
    try:
        summary = run_batch(
            path=Path(args.path),
            log_path=Path(args.log) if args.log else None,
            dry_run=args.dry_run,
            force=args.force,
            min_content_chars=args.min_content_chars,
            limit=args.limit,
            headless=not args.headed,
            api_key=api_key,
            model=model,
            ocr_backend=args.ocr_backend
            or os.environ.get("IMAGE_OCR_BACKEND", "")
            or read_config_str(ocr_config, "backend", DEFAULT_OCR_BACKEND),
            ocr_method=args.ocr_method
            or os.environ.get("IMAGE_OCR_METHOD", "")
            or read_config_str(ocr_config, "method", DEFAULT_OCR_METHOD),
            prompt_type=args.prompt_type
            or os.environ.get("IMAGE_OCR_PROMPT_TYPE", "")
            or read_config_str(ocr_config, "prompt-type", DEFAULT_PROMPT_TYPE),
            max_output_tokens=max_output_tokens,
            include_headers_footers=args.include_headers_footers
            or os.environ.get("IMAGE_OCR_INCLUDE_HEADERS_FOOTERS", "").strip().lower() in {"true", "1", "yes", "on"}
            or read_config_bool(ocr_config, "include-headers-footers"),
        )
    except (FileNotFoundError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
