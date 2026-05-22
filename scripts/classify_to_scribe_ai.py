from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _gemini_client import GeminiClient


CATEGORY_OPTIONS = [
    "Claude Code",
    "生活妙招",
    "好笑的",
    "LingOrm",
    "日文學習",
    "泰百",
    "健身",
    "身體健康",
    "心理健康",
    "動漫",
    "歷史",
    "政治",
    "科技",
    "旅遊",
    "職場",
    "美食",
    "AI",
    "Threads",
]
_CATEGORY_OPTION_SET = set(CATEGORY_OPTIONS)
_CATEGORY_CANONICAL_BY_CASEFOLD = {c.casefold(): c for c in CATEGORY_OPTIONS}
_CATEGORY_PREFIX_RE = re.compile(r"^(?:分類|category)\s*[:：]\s*", re.IGNORECASE)
_LEADING_WRAP_RE = re.compile(r'^[\s`"\'「『（(\[]+')
_TRAILING_WRAP_RE = re.compile(r'[\s`"\'」』）)\]]+$')

LINGORM_DEFINITION = (
    "LingOrm：與泰國藝人／CP Ling、Orm、00k、หลิง、ออม、LingOrm 相關的粉絲內容、"
    "劇情對話、訪談、剪輯、花絮、互動、迷因，都歸類為 LingOrm；"
    "即使內容同時很好笑，也優先輸出 LingOrm，不要輸出 好笑的。"
)

DEFAULT_AI_CATEGORIES = {"AI", "科技"}
DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass
class ClassifiedItem:
    post_id: str
    post_url: str
    decision: str
    confidence: float
    reason: str
    classified_at: str


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


def build_prompt(author_handle: str, content_text: str) -> str:
    return (
        "請從以下分類中只選一個最適合的分類。\n"
        "只能輸出分類名稱本身，不要解釋、不要標點、不要額外文字。\n\n"
        f"可選分類：{'、'.join(CATEGORY_OPTIONS)}\n\n"
        "分類判別補充：\n"
        f"- {LINGORM_DEFINITION}\n"
        "- 如果內容是戀愛、情侶、放閃、曖昧、超甜、愛情故事這類 romance / CP 內容，優先輸出 LingOrm。\n"
        "- 如果內容在談面試、求職、履歷、STAR/CARL 回答框架、hiring manager、recruiter、升職或職場建議，優先輸出 職場。\n"
        "- 如果內容在談 neurodivergent、ADHD、自閉症、burnout、焦慮、憂鬱、情緒照顧或心理狀態，優先輸出 心理健康。\n"
        "- 如果內容明確談論 Claude Code、CLAUDE.md、Codex（AI agent）、Claude Code skill 或 hook，優先輸出 Claude Code，不要輸出 AI 或 科技。\n"
        "- 如果內容在談 AI、agent、skill、prompt、workflow、LLM 工具（例如 GPT 指令技巧、Gemini 個人化設定）或把這些整合進服務，優先輸出 AI，不要輸出 科技。\n"
        "- 如果內容明確屬於特定 fandom / CP 主題，優先輸出該主題分類，不要只因為內容好笑就歸到 好笑的。\n\n"
        f"作者：{author_handle}\n"
        f"內容：{content_text[:5000]}"
    )


def normalize_category(raw_category: str) -> str:
    for line in raw_category.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        without_prefix = _CATEGORY_PREFIX_RE.sub("", candidate)
        normalized = _LEADING_WRAP_RE.sub("", without_prefix)
        normalized = _TRAILING_WRAP_RE.sub("", normalized)
        normalized = normalized.strip().rstrip("，。；：:,.!！?")
        if normalized:
            return _CATEGORY_CANONICAL_BY_CASEFOLD.get(normalized.casefold(), normalized)
    return ""


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_post(
    *,
    post: dict,
    client: GeminiClient,
    model: str,
    ai_categories: set[str],
) -> tuple[ClassifiedItem, str]:
    """Returns (item, category). category may be empty string on failure."""
    author = post.get("authorHandle", "") or ""
    content = post.get("contentText", "") or ""
    post_id = post.get("postId", "") or ""
    post_url = post.get("postUrl", "") or ""

    try:
        raw = client.generate_text(build_prompt(author, content), model=model)
    except Exception as error:
        return (
            ClassifiedItem(
                post_id=post_id,
                post_url=post_url,
                decision="unsure",
                confidence=0.0,
                reason=f"classifier error: {error}",
                classified_at=timestamp(),
            ),
            "",
        )

    category = normalize_category(raw)
    if category not in _CATEGORY_OPTION_SET:
        return (
            ClassifiedItem(
                post_id=post_id,
                post_url=post_url,
                decision="unsure",
                confidence=0.0,
                reason=f"invalid category from Gemini: {raw[:200]!r}",
                classified_at=timestamp(),
            ),
            "",
        )

    decision = "ai" if category in ai_categories else "not_ai"
    return (
        ClassifiedItem(
            post_id=post_id,
            post_url=post_url,
            decision=decision,
            confidence=1.0,
            reason=category,
            classified_at=timestamp(),
        ),
        category,
    )


def build_output_payload(
    *,
    source_file: str,
    model: str,
    posts: list[dict],
    classified: list[tuple[ClassifiedItem, str]],
    ai_categories: set[str],
) -> dict:
    items_out = []
    ai_count = 0
    not_ai_count = 0
    unsure_count = 0
    failed_count = 0

    for item, category in classified:
        if item.decision == "ai":
            ai_count += 1
            items_out.append(
                {
                    "postId": item.post_id,
                    "decision": item.decision,
                    "confidence": item.confidence,
                    "reason": item.reason,
                    "postUrl": item.post_url,
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
        "backend": f"crawl-the-threads/category_classifier ({model})",
        "aiCategories": sorted(ai_categories),
        "summary": {
            "total": len(posts),
            "ai": ai_count,
            "not_ai": not_ai_count,
            "unsure": unsure_count,
            "failed": failed_count,
        },
        "items": items_out,
    }


def parse_ai_categories(raw: str) -> set[str]:
    parts = [token.strip() for token in raw.split(",") if token.strip()]
    if not parts:
        return set(DEFAULT_AI_CATEGORIES)
    return set(parts)


def _pre_scan_env_file(argv: list[str]) -> str:
    for i, token in enumerate(argv):
        if token == "--env-file" and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith("--env-file="):
            return token.split("=", 1)[1]
    return ".env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify scribe.json posts via Gemini, emit scribe-ai.json")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--ai-categories", default=None)
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def main() -> int:
    load_dotenv(Path(_pre_scan_env_file(sys.argv[1:])))
    args = parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key.strip():
        print("ERROR: GEMINI_API_KEY missing. Set in .env or pass --api-key.", file=sys.stderr)
        return 2

    raw_categories = args.ai_categories or os.environ.get("AI_CATEGORIES", ",".join(sorted(DEFAULT_AI_CATEGORIES)))
    ai_categories = parse_ai_categories(raw_categories)
    input_path = Path(args.input or os.environ.get("SCRIBE_PATH", "data/scribe.json"))
    output_path = Path(args.output or os.environ.get("SCRIBE_AI_PATH", "data/scribe-ai.json"))
    model = args.model or os.environ.get("CLASSIFIER_MODEL", DEFAULT_MODEL)

    posts = load_posts(input_path)
    client = GeminiClient(api_key=api_key)

    classified: list[tuple[ClassifiedItem, str]] = []
    for index, post in enumerate(posts, start=1):
        print(f"[{index}/{len(posts)}] classifying {post.get('postId', '?')}", file=sys.stderr)
        classified.append(
            classify_post(
                post=post,
                client=client,
                model=model,
                ai_categories=ai_categories,
            )
        )

    payload = build_output_payload(
        source_file=input_path.name,
        model=model,
        posts=posts,
        classified=classified,
        ai_categories=ai_categories,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
