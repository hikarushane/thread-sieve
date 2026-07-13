from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

from note_generator.services.category_overrides import CategoryOverride, parse_category_overrides


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_INPUT_PATH = Path("data/catch.json")
DEFAULT_UNSAVE_PATH = Path("data/unsave.json")
DEFAULT_CONFIG_PATH = Path("config.json")
LEGACY_CONFIG_PATH = Path("classify_config.json")
DEFAULT_IMAGE_OCR_CATEGORIES = {"AI", "Claude Code"}
TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off"}

SUPPORTED_PROVIDERS = ("gemini", "anthropic", "openai")
DEFAULT_PROVIDER = "gemini"

_DEFAULT_TEXT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
}
_DEFAULT_VISION_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}
DEFAULT_GEMINI_MODEL = _DEFAULT_TEXT_MODELS["gemini"]  # back-compat re-export


@dataclass(frozen=True)
class AppConfig:
    input_path: Path
    unsave_path: Path
    output_dir: Path
    categories: list[str]
    unsaved_categories: set[str]
    hints: list[str]
    category_overrides: list[CategoryOverride]
    llm_provider: str
    llm_api_keys: dict[str, str]
    model_for_classification: str
    model_for_title: str
    model_for_ocr: str
    image_ocr_enabled: bool
    image_ocr_categories: set[str]
    playwright_enabled: bool
    playwright_headless: bool
    event_log_filename: str
    max_title_length: int = 80
    thread_context_enabled: bool = True
    thread_context_min_reply_chars: int = 12
    thread_context_max_replies: int = 30


def _load_dotenv_if_present(dotenv_path: Path | None) -> None:
    if dotenv_path is None or not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _resolve_from_project_root(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def resolve_json_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None and str(config_path).strip():
        return _resolve_from_project_root(config_path)

    configured = os.getenv("THREADSIEVE_CONFIG") or os.getenv("CLASSIFY_CONFIG")
    if configured and configured.strip():
        return _resolve_from_project_root(configured.strip())

    default_path = PROJECT_ROOT / DEFAULT_CONFIG_PATH
    legacy_path = PROJECT_ROOT / LEGACY_CONFIG_PATH
    if default_path.exists():
        return default_path
    if legacy_path.exists():
        return legacy_path
    return default_path


def load_json_config(config_path: str | Path | None = None) -> dict:
    path = resolve_json_config_path(config_path)
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_path_setting(config_data: dict, key: str, default: str = "") -> str:
    paths = config_data.get("paths", {})
    if not isinstance(paths, dict):
        return default

    value = paths.get(key)
    if value is None:
        return default

    text = str(value).strip()
    if not text:
        return default
    return os.path.expandvars(os.path.expanduser(text))


def read_str_list_setting(config_data: dict, key: str) -> list[str]:
    value = config_data.get(key)
    if not isinstance(value, list):
        return []
    return [str(part).strip() for part in value if str(part).strip()]


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        f"{name} must be one of: true/false, 1/0, yes/no, on/off"
    )


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")

    try:
        value = int(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")

    return value


def _read_csv_set(name: str, default: set[str]) -> set[str]:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return set(default)
    return {part.strip() for part in raw_value.split(",") if part.strip()}


def _read_thread_context_block(config_data: dict) -> dict:
    block = config_data.get("thread-context")
    return block if isinstance(block, dict) else {}


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if value > 0 else default


def _read_llm_block(config_data: dict) -> dict:
    block = config_data.get("llm")
    return block if isinstance(block, dict) else {}


def _resolve_provider(config_data: dict) -> str:
    env_value = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if env_value:
        return env_value
    block_value = str(_read_llm_block(config_data).get("provider") or "").strip().lower()
    if block_value:
        return block_value
    return DEFAULT_PROVIDER


def _resolve_model(
    config_data: dict,
    *,
    json_key: str,
    env_var: str,
    legacy_env_var: str | None,
    default_table: dict[str, str],
    provider: str,
) -> str:
    env_value = (os.getenv(env_var) or "").strip()
    if env_value:
        return env_value
    if legacy_env_var:
        legacy_value = (os.getenv(legacy_env_var) or "").strip()
        if legacy_value:
            return legacy_value
    block_value = str(_read_llm_block(config_data).get(json_key) or "").strip()
    if block_value:
        return block_value
    return default_table.get(provider, default_table[DEFAULT_PROVIDER])


def load_config(dotenv_path: Path | None = Path(".env")) -> AppConfig:
    _load_dotenv_if_present(dotenv_path)
    config_data = load_json_config()
    provider = _resolve_provider(config_data)

    api_keys = {
        "gemini": os.getenv("GEMINI_API_KEY", "").strip(),
        "anthropic": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "openai": os.getenv("OPENAI_API_KEY", "").strip(),
    }

    return AppConfig(
        input_path=Path(
            os.getenv("THREADS_BOOKMARK_INPUT")
            or os.getenv("CATCH_PATH")
            or read_path_setting(config_data, "catch-json", str(DEFAULT_INPUT_PATH))
        ),
        unsave_path=Path(
            os.getenv("UNSAVE_PATH")
            or read_path_setting(config_data, "unsave-json", str(DEFAULT_UNSAVE_PATH))
        ),
        output_dir=Path(
            os.getenv("THREADS_MARKDOWN_OUTPUT")
            or os.getenv("MARKDOWN_OUTPUT_PATH")
            or read_path_setting(config_data, "markdown-output-root", str(DEFAULT_OUTPUT_DIR))
        ),
        categories=read_str_list_setting(config_data, "categories"),
        unsaved_categories=set(read_str_list_setting(config_data, "unsaved-categories")),
        hints=read_str_list_setting(config_data, "hints"),
        category_overrides=parse_category_overrides(config_data),
        llm_provider=provider,
        llm_api_keys=api_keys,
        model_for_classification=_resolve_model(
            config_data,
            json_key="text-model",
            env_var="THREADS_LLM_CLASSIFIER_MODEL",
            legacy_env_var="CLASSIFIER_MODEL",
            default_table=_DEFAULT_TEXT_MODELS,
            provider=provider,
        ),
        model_for_title=_resolve_model(
            config_data,
            json_key="title-model",
            env_var="THREADS_LLM_TITLE_MODEL",
            legacy_env_var="THREADS_GEMINI_TITLE_MODEL",
            default_table=_DEFAULT_TEXT_MODELS,
            provider=provider,
        ),
        model_for_ocr=_resolve_model(
            config_data,
            json_key="vision-model",
            env_var="THREADS_LLM_OCR_MODEL",
            legacy_env_var="IMAGE_OCR_MODEL",
            default_table=_DEFAULT_VISION_MODELS,
            provider=provider,
        ),
        image_ocr_enabled=_read_bool("THREADS_IMAGE_OCR_ENABLED", False),
        image_ocr_categories=_read_csv_set(
            "THREADS_IMAGE_OCR_CATEGORIES",
            _read_csv_set("IMAGE_OCR_CATEGORIES", DEFAULT_IMAGE_OCR_CATEGORIES),
        ),
        playwright_enabled=_read_bool("THREADS_PLAYWRIGHT_ENABLED", True),
        playwright_headless=_read_bool("THREADS_PLAYWRIGHT_HEADLESS", True),
        event_log_filename=os.getenv("THREADS_EVENT_LOG_FILENAME", "threads_events.jsonl").strip()
        or "threads_events.jsonl",
        max_title_length=_read_positive_int("THREADS_MAX_TITLE_LENGTH", 80),
        thread_context_enabled=_read_bool(
            "THREADS_CONTEXT_ENABLED",
            _coerce_bool(_read_thread_context_block(config_data).get("enabled"), True),
        ),
        thread_context_min_reply_chars=_read_positive_int(
            "THREADS_CONTEXT_MIN_REPLY_CHARS",
            _coerce_positive_int(
                _read_thread_context_block(config_data).get("min-reply-chars"), 12
            ),
        ),
        thread_context_max_replies=_read_positive_int(
            "THREADS_CONTEXT_MAX_REPLIES",
            _coerce_positive_int(
                _read_thread_context_block(config_data).get("max-replies"), 30
            ),
        ),
    )
