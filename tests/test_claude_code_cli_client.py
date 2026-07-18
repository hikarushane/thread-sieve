from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from note_generator.infrastructure.claude_code_cli_client import ClaudeCodeCLIClient


@pytest.fixture(autouse=True)
def _cli_on_path(monkeypatch):
    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.shutil.which",
        lambda _: "/usr/local/bin/claude",
    )


def _make_client(**kwargs) -> ClaudeCodeCLIClient:
    return ClaudeCodeCLIClient(max_retries=0, **kwargs)


def _fake_run(captured, *, returncode=0, stdout="answer", stderr=""):
    def run(command, **kwargs):
        captured.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    return run


def test_missing_cli_raises(monkeypatch):
    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.shutil.which",
        lambda _: None,
    )
    with pytest.raises(RuntimeError, match="CLI not found"):
        ClaudeCodeCLIClient()


def test_generate_text_invokes_print_mode(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.subprocess.run",
        _fake_run(captured, stdout="  Tech \n"),
    )

    text = _make_client().generate_text("classify this", model_name="sonnet")

    assert text == "Tech"
    call = captured[0]
    assert call["command"] == [
        "claude", "-p", "--output-format", "text", "--model", "sonnet"
    ]
    assert call["input"] == "classify this"


def test_generate_text_omits_model_flag_when_empty(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.subprocess.run",
        _fake_run(captured),
    )

    _make_client().generate_text("prompt", model_name="")

    assert "--model" not in captured[0]["command"]


def test_generate_text_raises_on_nonzero_exit(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.subprocess.run",
        _fake_run(captured, returncode=1, stderr="not logged in"),
    )

    with pytest.raises(RuntimeError, match="not logged in"):
        _make_client().generate_text("prompt", model_name="")


def test_generate_text_retries_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def flaky_run(command, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="transient")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.subprocess.run", flaky_run
    )
    monkeypatch.setattr("note_generator.infrastructure.claude_code_cli_client.time.sleep", lambda _: None)

    client = ClaudeCodeCLIClient(max_retries=1)

    assert client.generate_text("prompt", model_name="") == "ok"
    assert calls["count"] == 2


def test_generate_text_from_image_writes_file_into_cwd(monkeypatch):
    captured = []

    def run(command, **kwargs):
        workdir = Path(kwargs["cwd"])
        captured.append(
            {
                "command": command,
                "input": kwargs["input"],
                "image_exists": (workdir / "image.jpg").exists(),
                "image_bytes": (workdir / "image.jpg").read_bytes(),
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout="ocr text", stderr="")

    monkeypatch.setattr(
        "note_generator.infrastructure.claude_code_cli_client.subprocess.run", run
    )

    text = _make_client().generate_text_from_image(b"jpegbytes", "transcribe", model_name="")

    assert text == "ocr text"
    call = captured[0]
    assert call["image_exists"] is True
    assert call["image_bytes"] == b"jpegbytes"
    assert "image.jpg" in call["input"]
    assert "transcribe" in call["input"]
