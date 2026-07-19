from __future__ import annotations

from pathlib import Path

from note_generator.models import ImportSummary

_STATUS_SUFFIX = {
    "written": "",
    "skipped": "（已存在，略過）",
    "failed": "（處理失敗）",
}


class ConsoleProgressReporter:
    """Print per-bookmark progress to stdout for the double-click launchers."""

    def start(self, total: int) -> None:
        print(f"共 {total} 個書籤，開始處理…", flush=True)

    def item(self, index: int, total: int, topic: str, category: str, status: str) -> None:
        suffix = _STATUS_SUFFIX.get(status, "")
        print(f"[{index}/{total}] {topic}  {category}{suffix}", flush=True)

    def finish(self, summary: ImportSummary, output_dir: Path) -> None:
        done = summary.written_count + summary.skipped_count
        line = (
            f"共 {summary.processed_count} 個書籤，"
            f"進度 {done}/{summary.processed_count}，"
            f"存檔路徑 {output_dir}"
        )
        if summary.failed_count:
            line += f"（失敗 {summary.failed_count} 筆）"
        print(line, flush=True)
