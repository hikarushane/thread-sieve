from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import Protocol
import re

from note_generator.config import AppConfig
from note_generator.domain.bookmark_reader import BookmarkReader
from note_generator.domain.filename_builder import FilenameBuilder
from note_generator.domain.markdown_content_builder import MarkdownContentBuilder
from note_generator.infrastructure.llm_factory import build_llm_client
from note_generator.models import ImportSummary
from note_generator.services.category_classifier import CategoryClassifier
from note_generator.services.event_logger import EventLogger
from note_generator.services.image_ocr_enricher import ImageOCREnricher
from note_generator.services.markdown_writer import MarkdownWriter
from note_generator.services.threads_reply_enricher import (
    PlaywrightThreadPageClient,
    ThreadsReplyEnricher,
)
from note_generator.services.title_generator import TitleGenerator
from note_generator.services.unsave_writer import build_unsave_payload, write_unsave_payload


logger = logging.getLogger(__name__)
_SOURCE_URL_LINE_RE = re.compile(r'^url:\s*"([^"]+)"\s*$', re.MULTILINE)


class _BookmarkReader(Protocol):
    def read(self) -> list[object]:
        ...


class _BookmarkEnricher(Protocol):
    def enrich(self, source: object) -> object:
        ...


class _BookmarkClassifier(Protocol):
    def classify(self, item: object) -> object:
        ...


class _ImageOCREnricher(Protocol):
    def enrich(self, item: object) -> object:
        ...


class _TitleGenerator(Protocol):
    def generate(self, item: object) -> object:
        ...


class _FilenameBuilder(Protocol):
    def build(self, title: str) -> str:
        ...


class _MarkdownBuilder(Protocol):
    def build(self, item: object, output_path: Path) -> object:
        ...


class _MarkdownWriter(Protocol):
    def write(self, document: object) -> Path:
        ...


class _WorkflowEventLogger(Protocol):
    def emit(self, event_type: str, **details: object) -> None:
        ...


class _DisabledThreadPageClient:
    def fetch_body_text(self, url: str) -> str:
        raise RuntimeError("Playwright enrichment disabled by configuration")

    def fetch_image_urls(self, url: str) -> list[str]:
        raise RuntimeError("Playwright image fetch disabled by configuration")


class _DisabledImageOCREnricher:
    def enrich(self, item: object) -> object:
        return item


class ImportBookmarksToMarkdownWorkflow:
    def __init__(
        self,
        *,
        reader: _BookmarkReader,
        enricher: _BookmarkEnricher,
        classifier: _BookmarkClassifier,
        ocr_enricher: _ImageOCREnricher,
        title_generator: _TitleGenerator,
        filename_builder: _FilenameBuilder,
        content_builder: _MarkdownBuilder,
        writer: _MarkdownWriter,
        output_dir: Path,
        event_logger: _WorkflowEventLogger,
        unsaved_categories: set[str] | None = None,
        unsave_output_path: Path | None = None,
        source_file_name: str = "catch.json",
        classification_model: str = "",
    ) -> None:
        self._reader = reader
        self._enricher = enricher
        self._classifier = classifier
        self._ocr_enricher = ocr_enricher
        self._title_generator = title_generator
        self._filename_builder = filename_builder
        self._content_builder = content_builder
        self._writer = writer
        self._output_dir = output_dir
        self._event_logger = event_logger
        self._unsaved_categories = unsaved_categories or set()
        self._unsave_output_path = unsave_output_path
        self._source_file_name = source_file_name
        self._classification_model = classification_model

    @classmethod
    def from_config(cls, config: AppConfig) -> "ImportBookmarksToMarkdownWorkflow":
        llm_client = build_llm_client(config.llm_provider, config.llm_api_keys)
        page_client = (
            PlaywrightThreadPageClient(headless=config.playwright_headless)
            if config.playwright_enabled
            else _DisabledThreadPageClient()
        )
        ocr_enricher = (
            ImageOCREnricher(
                llm_client=llm_client,
                model_name=config.model_for_ocr,
                trigger_categories=config.image_ocr_categories,
                image_page_client=page_client,
            )
            if config.image_ocr_enabled
            else _DisabledImageOCREnricher()
        )
        return cls(
            reader=BookmarkReader(config.input_path),
            enricher=ThreadsReplyEnricher(
                page_client=page_client,
                pre_content_label_lines=set(config.categories),
            ),
            classifier=CategoryClassifier(
                llm_client=llm_client,
                model_name=config.model_for_classification,
                categories=config.categories,
                hints=config.hints,
                category_overrides=config.category_overrides,
                provider=config.llm_provider,
            ),
            ocr_enricher=ocr_enricher,
            title_generator=TitleGenerator(
                llm_client=llm_client,
                model_name=config.model_for_title,
                max_title_length=config.max_title_length,
            ),
            filename_builder=FilenameBuilder(config.output_dir),
            content_builder=MarkdownContentBuilder(),
            writer=MarkdownWriter(dry_run=False),
            output_dir=config.output_dir,
            event_logger=EventLogger(config.output_dir / config.event_log_filename),
            unsaved_categories=config.unsaved_categories,
            unsave_output_path=config.unsave_path,
            source_file_name=config.input_path.name,
            classification_model=config.model_for_classification,
        )

    def run(self) -> ImportSummary:
        source_items = self._reader.read()
        existing_output_urls = self._load_existing_output_urls()
        written_count = 0
        skipped_count = 0
        failed_count = 0
        classification_failed_count = 0
        classified_items = []

        for source in source_items:
            classified = None

            self._event_logger.emit(
                "bookmark_parsed",
                post_url=source.post_url,
                author_handle=source.author_handle,
                status="ok",
            )

            try:
                enriched = self._enricher.enrich(source)
                self._event_logger.emit(
                    f"reply_fetch_{enriched.reply_fetch_status}",
                    post_url=source.post_url,
                    author_handle=source.author_handle,
                    status=enriched.reply_fetch_status,
                )

                classified = self._classifier.classify(enriched)
                classified_items.append(classified)

                if source.post_url in existing_output_urls:
                    skipped_count += 1
                    self._event_logger.emit(
                        "bookmark_skipped_existing",
                        post_url=source.post_url,
                        author_handle=source.author_handle,
                        status="skipped_existing",
                    )
                    continue

                classified = self._ocr_enricher.enrich(classified)
                titled = self._title_generator.generate(classified)
                filename = self._filename_builder.build(titled.generated_title)
                titled = replace(
                    titled,
                    resolved_filename=filename,
                )
                document = self._content_builder.build(
                    titled,
                    output_path=self._output_dir / filename,
                )
                written_path = self._writer.write(document)
                written_count += 1

                self._event_logger.emit(
                    "markdown_written",
                    post_url=source.post_url,
                    author_handle=source.author_handle,
                    status="ok",
                    output_path=str(written_path),
                )
                existing_output_urls.add(source.post_url)
            except Exception:
                failed_count += 1
                if classified is None:
                    classification_failed_count += 1
                logger.exception("Failed to process bookmark %s", source.post_url)
                self._event_logger.emit(
                    "bookmark_failed",
                    post_url=source.post_url,
                    author_handle=source.author_handle,
                    status="failed",
                )

        if self._unsave_output_path is not None:
            payload = build_unsave_payload(
                source_file=self._source_file_name,
                model=self._classification_model,
                total_count=len(source_items),
                classified=classified_items,
                unsaved_categories=self._unsaved_categories,
                failed_count=classification_failed_count,
            )
            write_unsave_payload(self._unsave_output_path, payload)

        summary = ImportSummary(
            processed_count=len(source_items),
            written_count=written_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
        logger.info("Workflow summary: %s", summary)
        return summary

    def _load_existing_output_urls(self) -> set[str]:
        if not self._output_dir.exists():
            return set()

        urls: set[str] = set()
        for path in self._output_dir.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue

            match = _SOURCE_URL_LINE_RE.search(text)
            if match:
                urls.add(match.group(1).strip())

        return urls
