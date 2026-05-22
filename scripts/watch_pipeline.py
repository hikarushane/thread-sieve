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
    note_project_path: Path,
    project_root: Path,
) -> None:
    parent_env = os.environ.copy()

    classify_env = parent_env.copy()
    classify_env["CATCH_PATH"] = str(scribe_path)
    classify_env["UNSAVE_PATH"] = str(scribe_ai_path)
    classify_args = [
        sys.executable,
        str(project_root / "scripts" / "classify_to_scribe_ai.py"),
        "--input", str(scribe_path),
        "--output", str(scribe_ai_path),
    ]

    note_env = parent_env.copy()
    note_env["THREADS_BOOKMARK_INPUT"] = str(scribe_path)
    note_args = [sys.executable, "app.py"]

    jobs = [
        ("classify", launch_job("classify", classify_args, cwd=project_root, env=classify_env)),
        ("notes", launch_job("notes", note_args, cwd=note_project_path, env=note_env)),
    ]
    wait_for_jobs(jobs)


def watch_loop(
    *,
    scribe_path: Path,
    scribe_ai_path: Path,
    note_project_path: Path,
    project_root: Path,
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
                                    note_project_path=note_project_path,
                                    project_root=project_root,
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
    parser = argparse.ArgumentParser(description="Watch catch.json and run classifier + note-importer in parallel.")
    parser.add_argument("--scribe", default=os.environ.get("CATCH_PATH", ""))
    parser.add_argument("--scribe-ai", default=os.environ.get("UNSAVE_PATH", ""))
    parser.add_argument("--note-project", default=os.environ.get("MARKDOWN_PATH", ""))
    parser.add_argument("--debounce", type=float, default=float(os.environ.get("DEBOUNCE_SECONDS", "2.0")))
    parser.add_argument("--poll", type=float, default=float(os.environ.get("POLL_SECONDS", "1.0")))
    parser.add_argument("--env-file", default=".env")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / args.env_file)

    scribe = args.scribe or os.environ.get("CATCH_PATH", "")
    scribe_ai = args.scribe_ai or os.environ.get("UNSAVE_PATH", "")
    note_project = args.note_project or os.environ.get("MARKDOWN_PATH", "")

    missing = [name for name, value in [("CATCH_PATH", scribe), ("UNSAVE_PATH", scribe_ai), ("MARKDOWN_PATH", note_project)] if not value]
    if missing:
        print(f"ERROR: missing required config: {', '.join(missing)}. Set in .env or pass via CLI.", file=sys.stderr)
        return 2

    return watch_loop(
        scribe_path=Path(scribe),
        scribe_ai_path=Path(scribe_ai),
        note_project_path=Path(note_project),
        project_root=PROJECT_ROOT,
        debounce_seconds=args.debounce,
        poll_seconds=args.poll,
    )


if __name__ == "__main__":
    raise SystemExit(main())
