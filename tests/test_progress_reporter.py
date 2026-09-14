from __future__ import annotations

from pathlib import Path

from note_generator.models import ImportSummary
from note_generator.services.progress_reporter import ConsoleProgressReporter


def test_start_announces_total(capsys) -> None:
    ConsoleProgressReporter().start(20)
    assert capsys.readouterr().out == "共 20 個書籤，開始處理…\n"


def test_item_written_line_has_index_topic_category(capsys) -> None:
    ConsoleProgressReporter().item(3, 20, "某個主題", "AI工具", "written")
    assert capsys.readouterr().out == "[3/20] 某個主題  AI工具\n"


def test_item_skipped_line_marks_existing(capsys) -> None:
    ConsoleProgressReporter().item(4, 20, "舊主題摘要", "美食", "skipped")
    assert capsys.readouterr().out == "[4/20] 舊主題摘要  美食（已存在，略過）\n"


def test_item_failed_line_marks_failure(capsys) -> None:
    ConsoleProgressReporter().item(5, 20, "壞掉的書籤", "—", "failed")
    assert capsys.readouterr().out == "[5/20] 壞掉的書籤  —（處理失敗）\n"


def test_finish_line_shows_total_progress_path(capsys) -> None:
    summary = ImportSummary(
        processed_count=20, written_count=15, skipped_count=3, failed_count=2
    )
    ConsoleProgressReporter().finish(summary, Path("/notes/out"))
    out = capsys.readouterr().out
    assert out == "共 20 個書籤，進度 18/20，存檔路徑 /notes/out（失敗 2 筆）\n"


def test_finish_line_without_failures_omits_failed_note(capsys) -> None:
    summary = ImportSummary(
        processed_count=2, written_count=2, skipped_count=0, failed_count=0
    )
    ConsoleProgressReporter().finish(summary, Path("/notes/out"))
    assert capsys.readouterr().out == "共 2 個書籤，進度 2/2，存檔路徑 /notes/out\n"


def test_zero_bookmarks_start_and_finish(capsys) -> None:
    ConsoleProgressReporter().start(0)
    assert capsys.readouterr().out == "共 0 個書籤，開始處理…\n"

    summary = ImportSummary(
        processed_count=0, written_count=0, skipped_count=0, failed_count=0
    )
    ConsoleProgressReporter().finish(summary, Path("/notes/out"))
    assert capsys.readouterr().out == "共 0 個書籤，進度 0/0，存檔路徑 /notes/out\n"


import json

from note_generator.services.progress_reporter import JsonlProgressReporter


def _lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


def test_jsonl_start_emits_total(capsys) -> None:
    JsonlProgressReporter().start(3)
    assert _lines(capsys) == [{"event": "start", "total": 3}]


def test_jsonl_item_written_includes_post_url_and_output_path(capsys) -> None:
    JsonlProgressReporter().item(
        1, 3, "Git Flow 比較", "開發工具", "written",
        post_url="https://www.threads.com/@a/post/X1",
        output_path="/notes/git-flow.md",
    )
    assert _lines(capsys) == [{
        "event": "item", "index": 1, "total": 3,
        "postUrl": "https://www.threads.com/@a/post/X1",
        "topic": "Git Flow 比較", "category": "開發工具", "status": "written",
        "outputPath": "/notes/git-flow.md",
    }]


def test_jsonl_item_skipped_omits_output_path(capsys) -> None:
    JsonlProgressReporter().item(2, 3, "舊主題", "美食", "skipped", post_url="u2")
    line = _lines(capsys)[0]
    assert line["status"] == "skipped"
    assert "outputPath" not in line


def test_jsonl_item_keeps_non_ascii(capsys) -> None:
    JsonlProgressReporter().item(2, 3, "中文主題", "分類", "failed", post_url="u")
    raw = capsys.readouterr().out
    assert "中文主題" in raw and "\\u" not in raw


def test_jsonl_finish_emits_summary(capsys) -> None:
    summary = ImportSummary(processed_count=3, written_count=1, skipped_count=1, failed_count=1)
    JsonlProgressReporter().finish(summary, Path("/notes/out"))
    assert _lines(capsys) == [{
        "event": "finish", "processed": 3, "written": 1, "skipped": 1, "failed": 1,
        "outputDir": "/notes/out",
    }]


def test_console_item_accepts_and_ignores_keyword_args(capsys) -> None:
    ConsoleProgressReporter().item(3, 20, "某個主題", "AI工具", "written", post_url="u", output_path="p")
    assert capsys.readouterr().out == "[3/20] 某個主題  AI工具\n"
