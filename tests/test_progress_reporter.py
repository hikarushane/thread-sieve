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
