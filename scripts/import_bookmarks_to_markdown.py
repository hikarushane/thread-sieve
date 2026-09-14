from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.config import load_config
from note_generator.workflows.import_bookmarks_to_markdown import ImportBookmarksToMarkdownWorkflow


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Threads bookmarks into local markdown notes.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--snapshots",
        default=None,
        help="Path to snapshots.json produced by the desktop app; replaces Playwright page fetches.",
    )
    parser.add_argument(
        "--progress",
        choices=("console", "jsonl"),
        default="console",
        help="Progress output format. jsonl emits one JSON object per line for machine consumers.",
    )
    return parser.parse_args(argv)


def build_workflow(config, args: argparse.Namespace) -> ImportBookmarksToMarkdownWorkflow:
    page_client = None
    if args.snapshots:
        from note_generator.services.snapshot_file_client import SnapshotFileThreadPageClient

        page_client = SnapshotFileThreadPageClient(Path(args.snapshots))

    progress_reporter = None
    if args.progress == "jsonl":
        from note_generator.services.progress_reporter import JsonlProgressReporter

        progress_reporter = JsonlProgressReporter()

    return ImportBookmarksToMarkdownWorkflow.from_config(
        config, page_client=page_client, progress_reporter=progress_reporter
    )


def main() -> None:
    args = parse_args()
    configure_logging()
    config = load_config(PROJECT_ROOT / args.env_file)
    workflow = build_workflow(config, args)
    summary = workflow.run()
    logging.getLogger(__name__).info(
        "Import complete: processed=%s written=%s skipped=%s failed=%s",
        summary.processed_count,
        summary.written_count,
        summary.skipped_count,
        summary.failed_count,
    )


if __name__ == "__main__":
    main()
