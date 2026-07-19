from __future__ import annotations

import json
from pathlib import Path

from note_generator.domain.markdown_content_builder import MarkdownContentBuilder
from note_generator.models import (
    ClassifiedBookmark,
    EnrichedBookmark,
    MarkdownDocumentOutput,
    SourceBookmark,
    TitledBookmark,
)
from note_generator.workflows.import_bookmarks_to_markdown import ImportBookmarksToMarkdownWorkflow


class FakeReader:
    def __init__(self, items: list[SourceBookmark]) -> None:
        self.items = items

    def read(self) -> list[SourceBookmark]:
        return self.items


class FakeEnricher:
    def enrich(self, source: SourceBookmark) -> EnrichedBookmark:
        return EnrichedBookmark(source=source, primary_content=source.content_text)


class FakeClassifier:
    def __init__(self, categories_by_post_id: dict[str, str]) -> None:
        self.categories_by_post_id = categories_by_post_id
        self.calls: list[str] = []

    def classify(self, item: EnrichedBookmark) -> ClassifiedBookmark:
        post_id = str(item.source.metadata["postId"])
        self.calls.append(post_id)
        return ClassifiedBookmark(
            enriched=item,
            category=self.categories_by_post_id[post_id],
            category_reason="test",
        )


class FakeOcrEnricher:
    def enrich(self, item: ClassifiedBookmark) -> ClassifiedBookmark:
        return item


class FakeTitleGenerator:
    def generate(self, item: ClassifiedBookmark) -> TitledBookmark:
        post_id = str(item.enriched.source.metadata["postId"])
        return TitledBookmark(classified=item, generated_title=f"title-{post_id}")


class FakeFilenameBuilder:
    def build(self, title: str) -> str:
        return f"{title}.md"


class FakeWriter:
    def write(self, document: MarkdownDocumentOutput) -> Path:
        document.output_path.parent.mkdir(parents=True, exist_ok=True)
        document.output_path.write_text(document.markdown_body, encoding="utf-8")
        return document.output_path


class FakeEventLogger:
    def emit(self, event_type: str, **details: object) -> None:
        pass


def test_workflow_writes_markdown_and_unsave_from_one_classification_pass(tmp_path: Path) -> None:
    output_dir = tmp_path / "notes"
    unsave_path = tmp_path / "unsave.json"
    items = [
        SourceBookmark(
            post_url="https://threads/post/1",
            author_handle="@demo",
            content_text="AI topic",
            metadata={"postId": "p_ai"},
        ),
        SourceBookmark(
            post_url="https://threads/post/2",
            author_handle="@demo",
            content_text="Food topic",
            metadata={"postId": "p_food"},
        ),
    ]
    classifier = FakeClassifier({"p_ai": "AI", "p_food": "Food"})
    workflow = ImportBookmarksToMarkdownWorkflow(
        reader=FakeReader(items),
        enricher=FakeEnricher(),
        classifier=classifier,
        ocr_enricher=FakeOcrEnricher(),
        title_generator=FakeTitleGenerator(),
        filename_builder=FakeFilenameBuilder(),
        content_builder=MarkdownContentBuilder(),
        writer=FakeWriter(),
        output_dir=output_dir,
        event_logger=FakeEventLogger(),
        unsaved_categories={"AI"},
        unsave_output_path=unsave_path,
        source_file_name="catch.json",
        classification_model="test-model",
    )

    summary = workflow.run()

    assert summary.written_count == 2
    assert classifier.calls == ["p_ai", "p_food"]
    assert (output_dir / "title-p_ai.md").exists()
    assert (output_dir / "title-p_food.md").exists()

    payload = json.loads(unsave_path.read_text(encoding="utf-8"))
    assert payload["sourceFile"] == "catch.json"
    assert payload["unsavedCategories"] == ["AI"]
    assert payload["summary"] == {
        "total": 2,
        "unsave": 1,
        "keep": 1,
        "unsure": 0,
        "failed": 0,
    }
    assert payload["items"][0]["postId"] == "p_ai"
    assert payload["items"][0]["reason"] == "AI"


def test_from_config_builds_workflow_for_each_provider(monkeypatch, tmp_path):
    """from_config must compile against AppConfig and propagate llm_provider to CategoryClassifier."""
    import pytest

    from note_generator.config import AppConfig

    captured_providers: list[str] = []

    def fake_factory(provider: str, api_keys):
        captured_providers.append(provider)

        class _StubClient:
            def generate_text(self, prompt: str, *, model_name: str) -> str:
                return ""

            def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
                return ""

        return _StubClient()

    monkeypatch.setattr(
        "note_generator.workflows.import_bookmarks_to_markdown.build_llm_client",
        fake_factory,
    )

    catch_path = tmp_path / "catch.json"
    catch_path.write_text("[]", encoding="utf-8")
    unsave_path = tmp_path / "unsave.json"
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    for provider in ("gemini", "anthropic", "openai"):
        cfg = AppConfig(
            input_path=catch_path,
            unsave_path=unsave_path,
            output_dir=output_dir,
            categories=["AI", "Tech"],
            unsaved_categories=set(),
            hints=[],
            category_overrides=[],
            llm_provider=provider,
            llm_api_keys={"gemini": "g", "anthropic": "a", "openai": "o"},
            model_for_classification="m-classify",
            model_for_title="m-title",
            model_for_ocr="m-ocr",
            image_ocr_enabled=False,
            image_ocr_categories=set(),
            playwright_enabled=False,
            playwright_headless=True,
            event_log_filename="threads_events.jsonl",
        )

        workflow = ImportBookmarksToMarkdownWorkflow.from_config(cfg)

        assert isinstance(workflow, ImportBookmarksToMarkdownWorkflow)
        assert workflow._classifier._provider == provider
        assert workflow._classifier._model_name == "m-classify"
        assert workflow._title_generator._model_name == "m-title"
        assert workflow._classification_model == "m-classify"

    assert captured_providers == ["gemini", "anthropic", "openai"]


def test_disabled_thread_page_client_raises_on_snapshot() -> None:
    from note_generator.workflows.import_bookmarks_to_markdown import _DisabledThreadPageClient
    import pytest

    client = _DisabledThreadPageClient()
    with pytest.raises(RuntimeError):
        client.fetch_page_snapshot("https://www.threads.com/@x/post/Y")


def test_from_config_passes_thread_context_settings(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"categories": ["Tech"], "thread-context": '
        '{"enabled": false, "min-reply-chars": 20, "max-replies": 5}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("THREADSIEVE_CONFIG", str(config_path))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    for name in (
        "THREADS_CONTEXT_ENABLED",
        "THREADS_CONTEXT_MIN_REPLY_CHARS",
        "THREADS_CONTEXT_MAX_REPLIES",
    ):
        monkeypatch.delenv(name, raising=False)

    from note_generator.config import load_config
    from note_generator.workflows.import_bookmarks_to_markdown import (
        ImportBookmarksToMarkdownWorkflow,
    )

    workflow = ImportBookmarksToMarkdownWorkflow.from_config(load_config(dotenv_path=None))
    enricher = workflow._enricher
    assert enricher._thread_context_enabled is False
    assert enricher._min_reply_chars == 20
    assert enricher._max_replies == 5


def test_workflow_end_to_end_with_reply_context(tmp_path) -> None:
    import json as _json

    from note_generator.services.threads_reply_enricher import PageSnapshot, ThreadsReplyEnricher

    blob = _json.dumps({
        "data": {
            "edges": [
                {"node": {"thread_items": [
                    {"post": {"code": "ROOT01", "user": {"username": "original_poster"},
                              "caption": {"text": "母帖脈絡文字"}, "text_post_app_info": {}}},
                    {"post": {"code": "FOCAL01", "user": {"username": "replier_b"},
                              "caption": {"text": "收藏的回應完整全文"},
                              "text_post_app_info": {"reply_to_author": {"username": "original_poster"}}}},
                ]}},
                {"node": {"thread_items": [
                    {"post": {"code": "C1", "user": {"username": "commenter_c"},
                              "caption": {"text": "路人問題"},
                              "text_post_app_info": {"reply_to_author": {"username": "original_poster"}}}},
                    {"post": {"code": "OPR1", "user": {"username": "original_poster"},
                              "caption": {"text": "原作者的回答"},
                              "text_post_app_info": {"reply_to_author": {"username": "commenter_c"}}}},
                ]}},
            ]
        }
    })

    class SnapshotClient:
        def fetch_page_snapshot(self, url: str) -> PageSnapshot:
            return PageSnapshot(body_text="", embedded_json_blobs=[blob])

        def fetch_body_text(self, url: str) -> str:
            return ""

        def fetch_image_urls(self, url: str) -> list[str]:
            return []

    output_dir = tmp_path / "notes"
    items = [
        SourceBookmark(
            post_url="https://www.threads.com/@replier_b/post/FOCAL01",
            author_handle="@replier_b",
            content_text="收藏的回應（DOM 截斷版）",
            metadata={"postId": "p_reply"},
        ),
    ]
    workflow = ImportBookmarksToMarkdownWorkflow(
        reader=FakeReader(items),
        enricher=ThreadsReplyEnricher(page_client=SnapshotClient()),
        classifier=FakeClassifier({"p_reply": "AI"}),
        ocr_enricher=FakeOcrEnricher(),
        title_generator=FakeTitleGenerator(),
        filename_builder=FakeFilenameBuilder(),
        content_builder=MarkdownContentBuilder(),
        writer=FakeWriter(),
        output_dir=output_dir,
        event_logger=FakeEventLogger(),
    )
    summary = workflow.run()

    assert summary.written_count == 1
    body = (output_dir / "title-p_reply.md").read_text(encoding="utf-8")
    assert 'saved_kind: "reply"' in body
    assert "收藏的回應完整全文" in body
    assert "## 上文脈絡" in body
    assert "> **@original_poster**（原帖）：" in body
    assert "> [!quote]- 回覆（2 則，含原作者 1 則）" in body


class FakeProgressReporter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, total: int) -> None:
        self.calls.append(("start", total))

    def item(self, index: int, total: int, topic: str, category: str, status: str) -> None:
        self.calls.append(("item", index, total, topic, category, status))

    def finish(self, summary, output_dir) -> None:
        self.calls.append(("finish", summary.processed_count, str(output_dir)))


def _make_items() -> list[SourceBookmark]:
    return [
        SourceBookmark(
            post_url="https://threads/post/1",
            author_handle="@demo",
            content_text="AI topic",
            metadata={"postId": "p_ai"},
        ),
        SourceBookmark(
            post_url="https://threads/post/2",
            author_handle="@demo",
            content_text="Food topic",
            metadata={"postId": "p_food"},
        ),
    ]


def _make_workflow(tmp_path: Path, reporter, categories: dict[str, str]):
    return ImportBookmarksToMarkdownWorkflow(
        reader=FakeReader(_make_items()),
        enricher=FakeEnricher(),
        classifier=FakeClassifier(categories),
        ocr_enricher=FakeOcrEnricher(),
        title_generator=FakeTitleGenerator(),
        filename_builder=FakeFilenameBuilder(),
        content_builder=MarkdownContentBuilder(),
        writer=FakeWriter(),
        output_dir=tmp_path / "notes",
        event_logger=FakeEventLogger(),
        progress_reporter=reporter,
    )


def test_workflow_reports_written_and_skipped_progress(tmp_path: Path) -> None:
    output_dir = tmp_path / "notes"
    output_dir.mkdir(parents=True)
    # post/1 已存在於輸出資料夾 → 會走 skipped 分支
    (output_dir / "existing.md").write_text(
        'url: "https://threads/post/1"\n', encoding="utf-8"
    )
    reporter = FakeProgressReporter()
    workflow = _make_workflow(
        tmp_path, reporter, {"p_ai": "AI", "p_food": "Food"}
    )

    workflow.run()

    assert reporter.calls == [
        ("start", 2),
        ("item", 1, 2, "AI topic", "AI", "skipped"),
        ("item", 2, 2, "title-p_food", "Food", "written"),
        ("finish", 2, str(output_dir)),
    ]


def test_workflow_reports_failed_progress_with_snippet(tmp_path: Path) -> None:
    reporter = FakeProgressReporter()
    # p_food 不在分類表 → FakeClassifier raise KeyError → failed 分支，classified 為 None
    workflow = _make_workflow(tmp_path, reporter, {"p_ai": "AI"})

    workflow.run()

    assert reporter.calls[1] == ("item", 1, 2, "title-p_ai", "AI", "written")
    assert reporter.calls[2] == ("item", 2, 2, "Food topic", "—", "failed")


def test_workflow_without_reporter_still_runs(tmp_path: Path) -> None:
    workflow = _make_workflow(tmp_path, None, {"p_ai": "AI", "p_food": "Food"})
    # progress_reporter=None（預設情境）不得炸掉
    summary = workflow.run()
    assert summary.written_count == 2


def test_topic_snippet_truncates_and_flattens() -> None:
    from note_generator.workflows.import_bookmarks_to_markdown import _topic_snippet

    assert _topic_snippet("短句") == "短句"
    assert _topic_snippet("第一行\n第二行") == "第一行 第二行"
    long_text = "字" * 40
    assert _topic_snippet(long_text) == "字" * 29 + "…"
    assert len(_topic_snippet(long_text)) == 30
