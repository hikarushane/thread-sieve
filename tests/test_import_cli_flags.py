from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def cli(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"categories": ["AI", "Tech"]}', encoding="utf-8")
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(config_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("THREADS_PLAYWRIGHT_ENABLED", "false")
    module = importlib.import_module("scripts.import_bookmarks_to_markdown")
    return module


def test_parse_args_defaults(cli) -> None:
    args = cli.parse_args([])
    assert args.snapshots is None
    assert args.progress == "console"


def test_parse_args_accepts_snapshots_and_jsonl(cli) -> None:
    args = cli.parse_args(["--snapshots", "/tmp/s.json", "--progress", "jsonl"])
    assert args.snapshots == "/tmp/s.json"
    assert args.progress == "jsonl"


def test_parse_args_rejects_unknown_progress(cli) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--progress", "xml"])


def test_build_workflow_wires_snapshot_client_and_jsonl_reporter(cli, tmp_path: Path) -> None:
    from note_generator.config import load_config
    from note_generator.services.progress_reporter import JsonlProgressReporter
    from note_generator.services.snapshot_file_client import SnapshotFileThreadPageClient

    snapshots = tmp_path / "snapshots.json"
    snapshots.write_text(json.dumps({"generatedAt": "", "items": {}}), encoding="utf-8")
    config = load_config(dotenv_path=None)
    args = cli.parse_args(["--snapshots", str(snapshots), "--progress", "jsonl"])
    workflow = cli.build_workflow(config, args)
    assert isinstance(workflow._progress_reporter, JsonlProgressReporter)
    assert isinstance(workflow._enricher._page_client, SnapshotFileThreadPageClient)


def test_build_workflow_defaults_keep_console_reporter(cli) -> None:
    from note_generator.config import load_config
    from note_generator.services.progress_reporter import ConsoleProgressReporter

    config = load_config(dotenv_path=None)
    workflow = cli.build_workflow(config, cli.parse_args([]))
    assert isinstance(workflow._progress_reporter, ConsoleProgressReporter)


def test_build_workflow_rejects_missing_snapshots_path(cli, tmp_path: Path) -> None:
    from note_generator.config import load_config

    missing = tmp_path / "does-not-exist.json"
    config = load_config(dotenv_path=None)
    args = cli.parse_args(["--snapshots", str(missing)])
    with pytest.raises(SystemExit):
        cli.build_workflow(config, args)
