from __future__ import annotations

from note_generator.models import EnrichedBookmark, SourceBookmark, ThreadPost


def _source() -> SourceBookmark:
    return SourceBookmark(
        post_url="https://www.threads.com/@replier_b/post/FOCAL01",
        author_handle="@replier_b",
        content_text="收藏的回應內容",
    )


def test_enriched_bookmark_defaults_keep_backward_compat() -> None:
    enriched = EnrichedBookmark(source=_source(), primary_content="收藏的回應內容")
    assert enriched.ancestor_chain == []
    assert enriched.reply_threads == []
    assert enriched.saved_kind == "root"
    assert enriched.reply_threads_truncated is False
    assert enriched.llm_content == enriched.combined_content


def test_llm_content_prepends_ancestor_chain_with_handles() -> None:
    chain = [
        ThreadPost(code="ROOT01", author_handle="original_poster", text="母帖全文"),
        ThreadPost(
            code="MID01",
            author_handle="replier_a",
            text="中間層回覆",
            reply_to_handle="original_poster",
        ),
    ]
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        ancestor_chain=chain,
        saved_kind="reply",
    )
    expected = (
        "[上文脈絡]\n"
        "@original_poster：母帖全文\n\n"
        "@replier_a：中間層回覆\n\n"
        "[收藏內容]\n"
        "收藏的回應內容"
    )
    assert enriched.llm_content == expected


def test_llm_content_excludes_reply_threads() -> None:
    enriched = EnrichedBookmark(
        source=_source(),
        primary_content="收藏的回應內容",
        reply_threads=[[ThreadPost(code="C1", author_handle="commenter_c", text="路人留言")]],
    )
    assert "路人留言" not in enriched.llm_content
