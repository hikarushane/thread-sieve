from __future__ import annotations

import sys
import time
from pathlib import Path
from threading import Thread

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import watch_pipeline as mod  # noqa: E402


def test_is_stable_returns_true_when_file_unchanged(tmp_path):
    target = tmp_path / "scribe.json"
    target.write_text("[]", encoding="utf-8")
    assert mod.is_stable(target, debounce_seconds=0.4, poll_seconds=0.1) is True


def test_is_stable_returns_false_when_file_keeps_changing(tmp_path):
    target = tmp_path / "scribe.json"
    target.write_text("[]", encoding="utf-8")

    def keep_writing():
        for _ in range(20):
            target.write_text(f"[{time.time_ns()}]", encoding="utf-8")
            time.sleep(0.05)

    writer = Thread(target=keep_writing, daemon=True)
    writer.start()
    try:
        result = mod.is_stable(target, debounce_seconds=0.6, poll_seconds=0.1)
    finally:
        writer.join(timeout=2.0)
    assert result is False


def test_is_stable_returns_false_when_file_missing(tmp_path):
    target = tmp_path / "missing.json"
    assert mod.is_stable(target, debounce_seconds=0.2, poll_seconds=0.05) is False


def test_load_dotenv_populates_environ(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n"
        "FOO=bar\n"
        'BAZ="quoted value"\n'
        "EMPTY=\n"
        "export EXPORTED=hello\n",
        encoding="utf-8",
    )
    for key in ("FOO", "BAZ", "EMPTY", "EXPORTED"):
        monkeypatch.delenv(key, raising=False)
    mod.load_dotenv(env_file)
    import os
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "quoted value"
    assert os.environ["EMPTY"] == ""
    assert os.environ["EXPORTED"] == "hello"


def test_load_dotenv_skips_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PRESET=fromfile\n", encoding="utf-8")
    monkeypatch.setenv("PRESET", "fromshell")
    mod.load_dotenv(env_file)
    import os
    assert os.environ["PRESET"] == "fromshell"


def test_load_dotenv_handles_missing_file(tmp_path):
    mod.load_dotenv(tmp_path / "nope.env")  # should not raise
