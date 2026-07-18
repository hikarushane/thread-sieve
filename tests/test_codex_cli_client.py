from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from note_generator.infrastructure.codex_cli_client import CodexCLIClient


@pytest.fixture(autouse=True)
def _cli_on_path(monkeypatch):
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.shutil.which",
        lambda _: "/usr/local/bin/codex",
    )


def _make_client(**kwargs) -> CodexCLIClient:
    return CodexCLIClient(max_retries=0, **kwargs)


def _last_message_path(command) -> Path:
    return Path(command[command.index("--output-last-message") + 1])


def _fake_run(captured, *, returncode=0, last_message="answer", stderr=""):
    def run(command, **kwargs):
        captured.append({"command": command, **kwargs})
        if last_message is not None:
            _last_message_path(command).write_text(last_message, encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=stderr)

    return run


def test_missing_cli_raises(monkeypatch):
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.shutil.which",
        lambda _: None,
    )
    with pytest.raises(RuntimeError, match="CLI not found"):
        CodexCLIClient()


def test_generate_text_invokes_exec_with_stdin_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.subprocess.run",
        _fake_run(captured, last_message="  Tech \n"),
    )

    text = _make_client().generate_text("classify this", model_name="gpt-5.1-codex")

    assert text == "Tech"
    command = captured[0]["command"]
    assert command[:2] == ["codex", "exec"]
    assert command[-1] == "-"
    assert ["--sandbox", "read-only"] == command[2:4]
    assert "--skip-git-repo-check" in command
    assert ["--model", "gpt-5.1-codex"] == command[command.index("--model"):command.index("--model") + 2]
    assert captured[0]["input"] == "classify this"


def test_generate_text_omits_model_flag_when_empty(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.subprocess.run",
        _fake_run(captured),
    )

    _make_client().generate_text("prompt", model_name="")

    assert "--model" not in captured[0]["command"]


def test_generate_text_raises_on_nonzero_exit(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.subprocess.run",
        _fake_run(captured, returncode=2, last_message=None, stderr="not logged in"),
    )

    with pytest.raises(RuntimeError, match="not logged in"):
        _make_client().generate_text("prompt", model_name="")


def test_generate_text_returns_empty_when_last_message_missing(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.codex_cli_client.subprocess.run",
        _fake_run(captured, last_message=None),
    )

    assert _make_client().generate_text("prompt", model_name="") == ""


def test_generate_text_retries_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def flaky_run(command, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="transient")
        _last_message_path(command).write_text("ok", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("note_generator.infrastructure.codex_cli_client.subprocess.run", flaky_run)
    monkeypatch.setattr("note_generator.infrastructure.codex_cli_client.time.sleep", lambda _: None)

    client = CodexCLIClient(max_retries=1)

    assert client.generate_text("prompt", model_name="") == "ok"
    assert calls["count"] == 2


def test_generate_text_from_image_passes_image_flag(monkeypatch):
    captured = []

    def run(command, **kwargs):
        image_path = Path(command[command.index("--image") + 1])
        captured.append(
            {
                "command": command,
                "input": kwargs["input"],
                "image_bytes": image_path.read_bytes(),
            }
        )
        _last_message_path(command).write_text("ocr text", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("note_generator.infrastructure.codex_cli_client.subprocess.run", run)

    text = _make_client().generate_text_from_image(b"jpegbytes", "transcribe", model_name="")

    assert text == "ocr text"
    assert captured[0]["image_bytes"] == b"jpegbytes"
    assert captured[0]["input"] == "transcribe"
    assert captured[0]["command"][-1] == "-"
