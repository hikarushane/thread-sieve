from __future__ import annotations

import sys
import time
from pathlib import Path
from threading import Thread

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import watch_pipeline as mod  # noqa: E402


def test_is_stable_returns_true_when_file_unchanged(tmp_path):
    target = tmp_path / "catch.json"
    target.write_text("[]", encoding="utf-8")
    assert mod.is_stable(target, debounce_seconds=0.4, poll_seconds=0.1) is True


def test_is_stable_returns_false_when_file_keeps_changing(tmp_path):
    target = tmp_path / "catch.json"
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


def test_run_pipeline_runs_ocr_after_classify_and_notes(monkeypatch, tmp_path):
    calls = []
    catch = tmp_path / "catch.json"
    unsave = tmp_path / "unsave.json"
    markdown_root = tmp_path / "markdown"

    class FakeProc:
        def __init__(self, name):
            self.name = name

        def wait(self):
            calls.append(("wait", self.name))
            return 0

    def fake_launch_job(name, args, *, cwd, env):
        calls.append(("launch", name, cwd, env.copy(), args))
        return FakeProc(name)

    monkeypatch.setattr(mod, "launch_job", fake_launch_job)
    monkeypatch.setenv("MARKDOWN_OUTPUT_PATH", str(markdown_root))

    mod.run_pipeline(
        scribe_path=catch,
        scribe_ai_path=unsave,
        project_root=Path("project-root"),
    )

    launched_names = [call[1] for call in calls if call[0] == "launch"]
    assert launched_names == ["classify", "notes", "ocr"]
    assert calls.index(("wait", "classify")) < launched_names.index("ocr") + 4
    notes_call = next(call for call in calls if call[0] == "launch" and call[1] == "notes")
    assert notes_call[2] == Path("project-root")
    assert notes_call[4] == [
        sys.executable,
        str(Path("project-root") / "scripts" / "import_bookmarks_to_markdown.py"),
    ]
    assert notes_call[3]["THREADS_BOOKMARK_INPUT"] == str(catch)
    assert notes_call[3]["THREADS_MARKDOWN_OUTPUT"] == str(markdown_root)
    ocr_call = next(call for call in calls if call[0] == "launch" and call[1] == "ocr")
    assert "--input" in ocr_call[4]
    assert "--classifications" in ocr_call[4]
    assert "--markdown-root" in ocr_call[4]


def test_resolve_markdown_output_path_defaults_inside_project(monkeypatch):
    monkeypatch.delenv("MARKDOWN_OUTPUT_PATH", raising=False)
    monkeypatch.delenv("THREADS_MARKDOWN_OUTPUT", raising=False)

    assert mod.resolve_markdown_output_path({}) == mod.PROJECT_ROOT / "output"


def test_resolve_markdown_output_path_reads_config_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("MARKDOWN_OUTPUT_PATH", raising=False)
    monkeypatch.delenv("THREADS_MARKDOWN_OUTPUT", raising=False)
    markdown_root = tmp_path / "notes"

    assert mod.resolve_markdown_output_path(
        {},
        {"paths": {"markdown-output-root": str(markdown_root)}},
    ) == markdown_root
