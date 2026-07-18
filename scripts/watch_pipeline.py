from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.config import (
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_UNSAVE_PATH,
    load_json_config,
    read_path_setting,
    resolve_json_config_path,
)

LOG_PATH = PROJECT_ROOT / "pipeline.log"


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


def log_line(message: str, *, log_file: Path | None = LOG_PATH) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] {message}"
    print(line)
    if log_file is not None:
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def stream_subprocess_output(proc: subprocess.Popen, *, prefix: str) -> None:
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        text = raw_line.rstrip()
        if text:
            log_line(f"{prefix} {text}")


def launch_job(name: str, args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    log_line(f"[{name}] starting: {' '.join(args)} (cwd={cwd})")
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    thread = Thread(target=stream_subprocess_output, args=(proc,), kwargs={"prefix": f"[{name}]"}, daemon=True)
    thread.start()
    return proc


def wait_for_jobs(jobs: list[tuple[str, subprocess.Popen]]) -> None:
    for name, proc in jobs:
        rc = proc.wait()
        log_line(f"[{name}] exit code: {rc}")


def resolve_markdown_output_path(env: dict[str, str], config_data: dict | None = None) -> Path:
    threads_output = env.get("THREADS_MARKDOWN_OUTPUT", "").strip()
    if threads_output:
        return Path(threads_output)

    explicit = env.get("MARKDOWN_OUTPUT_PATH", "").strip()
    if explicit:
        return Path(explicit)

    configured = read_path_setting(config_data or {}, "markdown-output-root", "")
    if configured:
        return Path(configured)

    return project_default_output_path()


def project_default_output_path() -> Path:
    return PROJECT_ROOT / DEFAULT_OUTPUT_DIR


def is_stable(path: Path, *, debounce_seconds: float, poll_seconds: float) -> bool:
    """Return True once mtime+size stays unchanged for `debounce_seconds`."""
    try:
        last = (path.stat().st_mtime_ns, path.stat().st_size)
    except FileNotFoundError:
        return False
    waited = 0.0
    while waited < debounce_seconds:
        time.sleep(poll_seconds)
        waited += poll_seconds
        try:
            current = (path.stat().st_mtime_ns, path.stat().st_size)
        except FileNotFoundError:
            return False
        if current != last:
            return False
    return True


def is_runnable_scribe(path: Path) -> tuple[bool, str]:
    """Return (ok, reason). Skip pipeline when catch.json is empty / not JSON / empty list."""
    try:
        if path.stat().st_size == 0:
            return False, "catch.json is empty (0 bytes)"
    except FileNotFoundError:
        return False, "catch.json missing"
    try:
        import json as _json
        payload = _json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return False, f"catch.json not valid JSON: {error!r}"
    items = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) == 0:
        return False, "catch.json has no items"
    return True, f"items={len(items)}"


def run_pipeline(
    *,
    scribe_path: Path,
    scribe_ai_path: Path,
    project_root: Path,
    config_data: dict | None = None,
    config_path: Path | None = None,
) -> None:
    parent_env = os.environ.copy()
    markdown_output_path = resolve_markdown_output_path(parent_env, config_data)

    note_env = parent_env.copy()
    note_env["THREADS_BOOKMARK_INPUT"] = str(scribe_path)
    note_env["UNSAVE_PATH"] = str(scribe_ai_path)
    note_env.setdefault("THREADS_MARKDOWN_OUTPUT", str(markdown_output_path))
    if config_path is not None:
        note_env["THREADSIEVE_CONFIG"] = str(config_path)
    note_args = [sys.executable, str(project_root / "scripts" / "import_bookmarks_to_markdown.py")]

    jobs = [
        ("notes", launch_job("notes", note_args, cwd=project_root, env=note_env)),
    ]
    wait_for_jobs(jobs)

    if parent_env.get("IMAGE_OCR_ENABLED", "true").strip().lower() in {"false", "0", "no", "off"}:
        log_line("[ocr] skipped: IMAGE_OCR_ENABLED=false")
        return

    ocr_env = parent_env.copy()
    ocr_args = [
        sys.executable,
        str(project_root / "scripts" / "image_ocr_to_markdown.py"),
        "--input", str(scribe_path),
        "--classifications", str(scribe_ai_path),
        "--markdown-root", str(markdown_output_path),
    ]
    if config_path is not None:
        ocr_args.extend(["--config", str(config_path)])
    wait_for_jobs([("ocr", launch_job("ocr", ocr_args, cwd=project_root, env=ocr_env))])


def watch_loop(
    *,
    scribe_path: Path,
    scribe_ai_path: Path,
    project_root: Path,
    config_data: dict | None,
    config_path: Path | None,
    debounce_seconds: float,
    poll_seconds: float,
) -> int:
    log_line(f"watching: {scribe_path}")
    last_stamp: tuple[int, int] | None = None

    while True:
        try:
            if scribe_path.exists():
                stat = scribe_path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
                if stamp != last_stamp:
                    log_line(f"change detected: mtime_ns={stamp[0]} size={stamp[1]}; waiting for debounce")
                    if is_stable(scribe_path, debounce_seconds=debounce_seconds, poll_seconds=poll_seconds):
                        last_stamp = stamp
                        ok, reason = is_runnable_scribe(scribe_path)
                        if not ok:
                            log_line(f"skip pipeline: {reason}")
                        else:
                            log_line(f"pipeline starting: {reason}")
                            try:
                                run_pipeline(
                                    scribe_path=scribe_path,
                                    scribe_ai_path=scribe_ai_path,
                                    project_root=project_root,
                                    config_data=config_data,
                                    config_path=config_path,
                                )
                            except Exception as error:
                                log_line(f"pipeline error: {error!r}")
                    else:
                        log_line("file still changing; will re-check on next poll")
            time.sleep(max(0.2, poll_seconds))
        except KeyboardInterrupt:
            log_line("interrupted; exiting watcher")
            return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch catch.json and run the local markdown importer.")
    parser.add_argument("--scribe", default=os.environ.get("CATCH_PATH", ""))
    parser.add_argument("--scribe-ai", default=os.environ.get("UNSAVE_PATH", ""))
    parser.add_argument("--config", default="")
    parser.add_argument("--debounce", type=float, default=float(os.environ.get("DEBOUNCE_SECONDS", "2.0")))
    parser.add_argument("--poll", type=float, default=float(os.environ.get("POLL_SECONDS", "1.0")))
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def _pre_scan_env_file(argv: list[str]) -> str:
    for i, token in enumerate(argv):
        if token == "--env-file" and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith("--env-file="):
            return token.split("=", 1)[1]
    return ".env"


def main() -> int:
    load_dotenv(PROJECT_ROOT / _pre_scan_env_file(sys.argv[1:]))
    args = parse_args()
    config_path = resolve_json_config_path(args.config)
    if not config_path.exists():
        print(f"ERROR: config not found at {config_path}. Copy config.json and edit it, then retry.", file=sys.stderr)
        return 2
    config_data = load_json_config(config_path)

    scribe = (
        args.scribe
        or os.environ.get("CATCH_PATH", "")
        or read_path_setting(config_data, "catch-json", str(DEFAULT_INPUT_PATH))
    )
    scribe_ai = (
        args.scribe_ai
        or os.environ.get("UNSAVE_PATH", "")
        or read_path_setting(config_data, "unsave-json", str(DEFAULT_UNSAVE_PATH))
    )

    missing = [name for name, value in [("paths.catch-json", scribe), ("paths.unsave-json", scribe_ai)] if not value]
    if missing:
        print(f"ERROR: missing required config: {', '.join(missing)}. Set in config.json or pass via CLI.", file=sys.stderr)
        return 2

    return watch_loop(
        scribe_path=Path(scribe),
        scribe_ai_path=Path(scribe_ai),
        project_root=PROJECT_ROOT,
        config_data=config_data,
        config_path=config_path,
        debounce_seconds=args.debounce,
        poll_seconds=args.poll,
    )


if __name__ == "__main__":
    raise SystemExit(main())
