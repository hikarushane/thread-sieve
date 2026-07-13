from __future__ import annotations

from pathlib import Path

from note_generator.domain.markdown_content_builder import MarkdownContentBuilder
from note_generator.models import (
    ClassifiedBookmark,
    EnrichedBookmark,
    SourceBookmark,
    ThreadPost,
    TitledBookmark,
)


def _titled(enriched: EnrichedBookmark) -> TitledBookmark:
    classified = ClassifiedBookmark(enriched=enriched, category="Tech")
    return TitledBookmark(classified=classified, generated_title="title")


def _source() -> SourceBookmark:
    return SourceBookmark(
        post_url="https://www.threads.com/@replier_b/post/FOCAL01",
        author_handle="@replier_b",
        content_text="收藏的回應內容",
    )


def _build(enriched: EnrichedBookmark) -> str:
    builder = MarkdownContentBuilder()
    document = builder.build(_titled(enriched), output_path=Path("out/note.md"))
    return document.markdown_body


def test_root_note_output_has_saved_kind_and_no_context_sections() -> None:
    body = _build(EnrichedBookmark(source=_source(), primary_content="收藏的回應內容"))
    assert 'saved_kind: "root"' in body
    assert "## 上文脈絡" not in body
    assert "[!quote]-" not in body
    assert body.endswith("收藏的回應內容\n")


def test_reply_note_renders_ancestor_chain_as_nested_blockquotes() -> None:
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        saved_kind="reply",
        ancestor_chain=[
            ThreadPost(code="ROOT01", author_handle="original_poster", text="母帖第一行\n母帖第二行"),
            ThreadPost(code="MID01", author_handle="replier_a", text="中間層", reply_to_handle="original_poster"),
        ],
    )
    body = _build(enriched)
    assert 'saved_kind: "reply"' in body
    assert "## 上文脈絡" in body
    assert "> **@original_poster**（原帖）：" in body
    assert "> 母帖第一行" in body
    assert "> 母帖第二行" in body
    assert "> > **@replier_a**：" in body
    assert "> > 中間層" in body
    # 主文在上文脈絡之前
    assert body.index("收藏的回應內容") < body.index("## 上文脈絡")


def test_reply_callout_pairs_op_reply_and_counts() -> None:
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        saved_kind="reply",
        ancestor_chain=[ThreadPost(code="ROOT01", author_handle="original_poster", text="母帖")],
        reply_threads=[
            [
                ThreadPost(code="C1", author_handle="commenter_c", text="路人問題", reply_to_handle="original_poster"),
                ThreadPost(code="OPR1", author_handle="original_poster", text="原作者的回答", reply_to_handle="commenter_c"),
            ],
        ],
    )
    body = _build(enriched)
    assert "> [!quote]- 回覆（2 則，含原作者 1 則）" in body
    assert "> - **@commenter_c**：路人問題" in body
    assert ">   - ↳ **@original_poster**（原作者）：原作者的回答" in body


def test_reply_callout_marks_truncation() -> None:
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        reply_threads=[[ThreadPost(code="C1", author_handle="commenter_c", text="有料留言")]],
        reply_threads_truncated=True,
    )
    body = _build(enriched)
    assert "，已截斷）" in body


def test_ocr_section_stays_between_content_and_context() -> None:
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        saved_kind="reply",
        ancestor_chain=[ThreadPost(code="ROOT01", author_handle="original_poster", text="母帖")],
    )
    classified = ClassifiedBookmark(enriched=enriched, category="Tech", ocr_texts=["圖片文字內容"])
    titled = TitledBookmark(classified=classified, generated_title="title")
    body = MarkdownContentBuilder().build(titled, output_path=Path("out/note.md")).markdown_body
    assert body.index("## 圖片文字") < body.index("## 上文脈絡")
