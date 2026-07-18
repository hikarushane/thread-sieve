from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable
from urllib import request

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.infrastructure.chandra_ocr import ChandraOcrEngine
from note_generator.infrastructure.llm_factory import build_llm_client
from note_generator.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_UNSAVE_PATH,
    load_json_config,
    read_path_setting,
    resolve_json_config_path,
)


DEFAULT_OCR_BACKEND = "gemini"
DEFAULT_OCR_METHOD = "vllm"
DEFAULT_MAX_OUTPUT_TOKENS = 12384
DEFAULT_TRIGGER_CATEGORIES = {"AI", "Claude Code"}
DEFAULT_PROMPT_TYPE = "ocr_layout"
DEFAULT_MODEL = "gemini-2.5-flash"
OCR_PROMPT = (
    "分析這張圖片的內容，以結構化 Markdown 格式輸出。規則：\n"
    "1. 程式碼截圖 → 用 fenced code block（附語言標籤），保留縮排\n"
    "2. 終端機/命令列輸出 → 用 ```text 或 ```bash code block\n"
    "3. 對話截圖（聊天、推文、留言串）→ 用引言格式（> ），標明發言者\n"
    "4. 圖表/流程圖 → 先用一句話描述，再列出關鍵節點或數據\n"
    "5. 一般文字 → 用適當的標題、列表、段落組織\n"
    "6. 混合內容 → 依各區塊類型分別處理\n"
    "直接輸出 Markdown，不要加前言或解釋。"
)
_OCR_SECTION_RE = re.compile(r"\n*## 圖片文字\n\n.*?(?=\n## |\Z)", re.DOTALL)


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


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_set(value: str, default: set[str]) -> set[str]:
    if not value.strip():
        return set(default)
    return {part.strip() for part in value.split(",") if part.strip()}


def read_configured_set(value: object, default: set[str]) -> set[str]:
    if isinstance(value, list):
        return {str(part).strip() for part in value if str(part).strip()}
    if isinstance(value, str):
        return read_csv_set(value, default)
    return set(default)


def read_int_env(*names: str, default: int) -> int:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return int(value)
    return default


def read_ocr_config(path: Path) -> dict:
    if not path.exists():
        return {}
    config = load_json_config(path)
    if not isinstance(config, dict):
        return {}
    image_ocr = config.get("image-ocr", {})
    return image_ocr if isinstance(image_ocr, dict) else {}


def read_config_str(config: dict, key: str, default: str) -> str:
    value = config.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def read_config_bool(config: dict, key: str, default: bool = False) -> bool:
    value = config.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return default


def read_config_int(config: dict, key: str, default: int) -> int:
    value = config.get(key)
    if value is None or str(value).strip() == "":
        return default
    return int(value)


def select_trigger_posts(posts: list[dict], classifications: dict, trigger_categories: set[str]) -> list[dict]:
    category_by_key: dict[str, str] = {}
    for item in classifications.get("items", []):
        category = item.get("reason", "")
        for key in (item.get("postId"), item.get("postUrl")):
            if key:
                category_by_key[str(key)] = category

    selected: list[dict] = []
    for post in posts:
        category = category_by_key.get(str(post.get("postId", ""))) or category_by_key.get(str(post.get("postUrl", "")))
        if category in trigger_categories:
            selected.append(post)
    return selected


def find_markdown_by_post_url(markdown_root: Path, post_url: str) -> Path | None:
    if not markdown_root.exists():
        return None
    for path in markdown_root.rglob("*.md"):
        try:
            if post_url in path.read_text(encoding="utf-8"):
                return path
        except OSError:
            continue
    return None


def apply_ocr_section(markdown_path: Path, ocr_texts: list[str]) -> None:
    if not ocr_texts:
        return
    text = markdown_path.read_text(encoding="utf-8")
    text = _OCR_SECTION_RE.sub("", text).rstrip()
    section = "## 圖片文字\n\n" + "\n\n---\n\n".join(t.strip() for t in ocr_texts if t.strip()) + "\n\n"
    sources_index = text.find("## Sources")
    if sources_index == -1:
        updated = text + "\n\n" + section
    else:
        updated = text[:sources_index].rstrip() + "\n\n" + section + text[sources_index:]
    if not updated.endswith("\n"):
        updated += "\n"
    markdown_path.write_text(updated, encoding="utf-8")


def extract_post_image_urls_from_dom_records(records: list[dict]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for record in records:
        src = str(record.get("src") or "")
        width = int(record.get("w") or 0)
        height = int(record.get("h") or 0)
        if "/v/t51.82787-15/" not in src:
            continue
        if width < 200 or height < 250:
            continue
        if src in seen:
            continue
        seen.add(src)
        urls.append(src)
    return urls


def fetch_image_urls_with_playwright(post_url: str, *, headless: bool = True) -> list[str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            records = page.evaluate(
                """() => Array.from(document.images).map((img) => ({
                    src: img.currentSrc || img.src,
                    w: img.naturalWidth,
                    h: img.naturalHeight,
                    alt: img.alt || "",
                }))"""
            )
            return extract_post_image_urls_from_dom_records(records)
        finally:
            browser.close()


def download_image(url: str) -> bytes:
    with request.urlopen(url, timeout=20) as response:
        return response.read()


def build_gemini_ocr_image(*, api_key: str, model: str = DEFAULT_MODEL) -> Callable[[str], str]:
    if not api_key.strip():
        raise RuntimeError("GEMINI_API_KEY missing. Set in .env or pass --api-key.")
    client = build_llm_client("gemini", {"gemini": api_key})

    def ocr_image(image_url: str) -> str:
        return client.generate_text_from_image(download_image(image_url), OCR_PROMPT, model_name=model)

    return ocr_image


def build_chandra_ocr_image(
    *,
    method: str = DEFAULT_OCR_METHOD,
    prompt_type: str = DEFAULT_PROMPT_TYPE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    include_headers_footers: bool = False,
) -> Callable[[str], str]:
    engine = ChandraOcrEngine(
        method=method,
        prompt_type=prompt_type,
        max_output_tokens=max_output_tokens,
        include_headers_footers=include_headers_footers,
    )

    def ocr_image(image_url: str) -> str:
        return engine.generate_markdown(download_image(image_url))

    return ocr_image


def build_ocr_image(
    *,
    backend: str = DEFAULT_OCR_BACKEND,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    ocr_method: str = DEFAULT_OCR_METHOD,
    prompt_type: str = DEFAULT_PROMPT_TYPE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    include_headers_footers: bool = False,
) -> Callable[[str], str]:
    normalized_backend = backend.strip().lower() or DEFAULT_OCR_BACKEND
    if normalized_backend == "gemini":
        return build_gemini_ocr_image(api_key=api_key, model=model)
    if normalized_backend == "chandra":
        return build_chandra_ocr_image(
            method=ocr_method,
            prompt_type=prompt_type,
            max_output_tokens=max_output_tokens,
            include_headers_footers=include_headers_footers,
        )
    raise RuntimeError(f"Unsupported IMAGE_OCR_BACKEND: {backend!r}. Use 'gemini' or 'chandra'.")


def ocr_post_images(*, post_url: str, ocr_image: Callable[[str], str], headless: bool = True) -> list[str]:
    texts: list[str] = []
    for image_url in fetch_image_urls_with_playwright(post_url, headless=headless):
        try:
            text = ocr_image(image_url)
        except Exception:
            continue
        if text.strip():
            texts.append(text.strip())
    return texts


def run(
    *,
    input_path: Path,
    classifications_path: Path,
    markdown_root: Path,
    trigger_categories: set[str],
    headless: bool,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    ocr_backend: str = DEFAULT_OCR_BACKEND,
    ocr_method: str = DEFAULT_OCR_METHOD,
    prompt_type: str = DEFAULT_PROMPT_TYPE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    include_headers_footers: bool = False,
) -> dict:
    posts = read_json(input_path)
    if not isinstance(posts, list):
        raise ValueError(f"{input_path} must contain a top-level JSON array")
    classifications = read_json(classifications_path)
    if not isinstance(classifications, dict):
        raise ValueError(f"{classifications_path} must contain a JSON object")

    ocr_image = build_ocr_image(
        backend=ocr_backend,
        api_key=api_key,
        model=model,
        ocr_method=ocr_method,
        prompt_type=prompt_type,
        max_output_tokens=max_output_tokens,
        include_headers_footers=include_headers_footers,
    )
    selected = select_trigger_posts(posts, classifications, trigger_categories)
    updated = 0
    skipped = 0
    for post in selected:
        post_url = str(post.get("postUrl") or "")
        if not post_url:
            skipped += 1
            continue
        markdown_path = find_markdown_by_post_url(markdown_root, post_url)
        if markdown_path is None:
            skipped += 1
            continue
        ocr_texts = ocr_post_images(post_url=post_url, ocr_image=ocr_image, headless=headless)
        if not ocr_texts:
            skipped += 1
            continue
        apply_ocr_section(markdown_path, ocr_texts)
        updated += 1

    return {"selected": len(selected), "updated": updated, "skipped": skipped}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR Threads post images and append ## 圖片文字 to markdown notes.")
    parser.add_argument("--input", default="")
    parser.add_argument("--classifications", default="")
    parser.add_argument("--markdown-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--ocr-backend", default="")
    parser.add_argument("--ocr-method", default="")
    parser.add_argument("--prompt-type", default="")
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--include-headers-footers", action="store_true")
    parser.add_argument("--trigger-categories", default="")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(Path(args.env_file))
    config_path = resolve_json_config_path(args.config)
    config_data = load_json_config(config_path)
    ocr_config = read_ocr_config(config_path)
    max_output_tokens = args.max_output_tokens
    if max_output_tokens is None:
        max_output_tokens = read_int_env(
            "IMAGE_OCR_MAX_OUTPUT_TOKENS",
            "MAX_OUTPUT_TOKENS",
            default=read_config_int(ocr_config, "max-output-tokens", DEFAULT_MAX_OUTPUT_TOKENS),
        )
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    model = args.model or os.environ.get("IMAGE_OCR_MODEL", DEFAULT_MODEL)
    configured_categories = read_configured_set(ocr_config.get("trigger-categories"), DEFAULT_TRIGGER_CATEGORIES)
    trigger_categories = read_csv_set(
        args.trigger_categories or os.environ.get("IMAGE_OCR_CATEGORIES", ""),
        configured_categories,
    )
    try:
        summary = run(
            input_path=Path(
                args.input
                or os.environ.get("CATCH_PATH")
                or read_path_setting(config_data, "catch-json", str(DEFAULT_INPUT_PATH))
            ),
            classifications_path=Path(
                args.classifications
                or os.environ.get("UNSAVE_PATH")
                or read_path_setting(config_data, "unsave-json", str(DEFAULT_UNSAVE_PATH))
            ),
            markdown_root=Path(
                args.markdown_root
                or os.environ.get("THREADS_MARKDOWN_OUTPUT")
                or os.environ.get("MARKDOWN_OUTPUT_PATH")
                or read_path_setting(config_data, "markdown-output-root", str(DEFAULT_OUTPUT_DIR))
            ),
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
            trigger_categories=trigger_categories,
            headless=not args.headed,
        )
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
