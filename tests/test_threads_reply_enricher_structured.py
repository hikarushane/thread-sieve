from __future__ import annotations

import json

from note_generator.models import SourceBookmark
from note_generator.services.threads_reply_enricher import PageSnapshot, ThreadsReplyEnricher


def _item(code: str, username: str, text: str, reply_to: str | None = None) -> dict:
    info: dict = {}
    if reply_to:
        info["reply_to_author"] = {"username": reply_to}
    return {
        "post": {
            "code": code,
            "user": {"username": username},
            "caption": {"text": text},
            "text_post_app_info": info,
        }
    }


def _blob(*chains: list[dict]) -> str:
    edges = [{"node": {"thread_items": chain}} for chain in chains]
    return json.dumps({"data": {"edges": edges}})


class FakeSnapshotClient:
    def __init__(self, snapshot: PageSnapshot | Exception) -> None:
        self._snapshot = snapshot

    def fetch_page_snapshot(self, url: str) -> PageSnapshot:
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot

    def fetch_body_text(self, url: str) -> str:
        snapshot = self.fetch_page_snapshot(url)
        return snapshot.body_text

    def fetch_image_urls(self, url: str) -> list[str]:
        return []


def _source(code: str = "FOCAL01", handle: str = "@replier_b") -> SourceBookmark:
    return SourceBookmark(
        post_url=f"https://www.threads.com/{handle}/post/{code}",
        author_handle=handle,
        content_text="收藏的回應（DOM 截斷版）",
    )


def _enricher(snapshot: PageSnapshot | Exception, **kwargs: object) -> ThreadsReplyEnricher:
    return ThreadsReplyEnricher(page_client=FakeSnapshotClient(snapshot), **kwargs)


def test_structured_path_extracts_ancestor_chain_and_saved_kind() -> None:
    blob = _blob([
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("MID01", "replier_a", "中間層回覆", reply_to="original_poster"),
        _item("FOCAL01", "replier_b", "收藏的回應完整全文", reply_to="replier_a"),
    ])
    enriched = _enricher(PageSnapshot(body_text="", embedded_json_blobs=[blob])).enrich(_source())

    assert enriched.reply_fetch_status == "fetched_structured"
    assert enriched.saved_kind == "reply"
    assert enriched.primary_content == "收藏的回應完整全文"
    assert [p.code for p in enriched.ancestor_chain] == ["ROOT01", "MID01"]


def test_structured_path_keeps_op_reply_with_paired_parent() -> None:
    blob = _blob(
        [
            _item("ROOT01", "original_poster", "母帖全文"),
            _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
        ],
        [
            _item("C1", "commenter_c", "短問", reply_to="original_poster"),
            _item("OPR1", "original_poster", "原作者的回答", reply_to="commenter_c"),
        ],
    )
    enriched = _enricher(
        PageSnapshot(body_text="", embedded_json_blobs=[blob]),
        min_reply_chars=12,
    ).enrich(_source())

    assert len(enriched.reply_threads) == 1
    kept = enriched.reply_threads[0]
    # 「短問」不足 12 字，但因 OP 回覆配對而保留
    assert [p.code for p in kept] == ["C1", "OPR1"]


def test_structured_path_filters_short_and_emoji_only_replies() -> None:
    blob = _blob(
        [
            _item("ROOT01", "original_poster", "母帖全文"),
            _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
        ],
        [_item("C1", "commenter_c", "👍👍👍", reply_to="original_poster")],
        [_item("C2", "commenter_d", "短", reply_to="original_poster")],
        [_item("C3", "commenter_e", "這是一則超過十二個字的有料留言喔", reply_to="original_poster")],
    )
    enriched = _enricher(PageSnapshot(body_text="", embedded_json_blobs=[blob])).enrich(_source())

    assert len(enriched.reply_threads) == 1
    assert enriched.reply_threads[0][0].code == "C3"


def test_saved_root_self_thread_goes_to_author_replies_not_reply_threads() -> None:
    blob = _blob(
        [_item("FOCAL01", "original_poster", "母帖全文")],
        [_item("SELF1", "original_poster", "自串第二段", reply_to="original_poster")],
    )
    source = _source(handle="@original_poster")
    enriched = _enricher(PageSnapshot(body_text="", embedded_json_blobs=[blob])).enrich(source)

    assert enriched.saved_kind == "root"
    assert enriched.author_replies == ["自串第二段"]
    assert enriched.reply_threads == []
    assert "自串第二段" in enriched.combined_content


def test_reply_threads_capped_and_marked_truncated() -> None:
    reply_chains = [
        [_item(f"C{i}", f"commenter_{i}", f"這是一則超過十二個字的有料留言第{i}號")]
        for i in range(5)
    ]
    blob = _blob([_item("FOCAL01", "original_poster", "母帖全文")], *reply_chains)
    enriched = _enricher(
        PageSnapshot(body_text="", embedded_json_blobs=[blob]),
        max_replies=3,
    ).enrich(_source(handle="@original_poster"))

    assert len(enriched.reply_threads) == 3
    assert enriched.reply_threads_truncated is True


def test_broken_json_falls_back_to_body_text_heuristic() -> None:
    body_text = (
        "replier_b\n"
        "3h\n"
        "收藏的回應（DOM 截斷版）\n"
    )
    enriched = _enricher(
        PageSnapshot(body_text=body_text, embedded_json_blobs=["{broken"]),
    ).enrich(_source())

    assert enriched.reply_fetch_status in {"fetched_fallback", "no_author_replies"}
    assert enriched.ancestor_chain == []


def test_disabled_thread_context_behaves_like_legacy() -> None:
    blob = _blob([_item("FOCAL01", "replier_b", "收藏的回應完整全文")])
    enriched = _enricher(
        PageSnapshot(body_text="", embedded_json_blobs=[blob]),
        thread_context_enabled=False,
    ).enrich(_source())

    assert enriched.reply_fetch_status in {"fetched", "no_author_replies"}
    assert enriched.ancestor_chain == []
    assert enriched.saved_kind == "root"


def test_fetch_failure_falls_back_to_primary() -> None:
    enriched = _enricher(RuntimeError("network down")).enrich(_source())
    assert enriched.reply_fetch_status == "fallback_to_primary"
    assert enriched.primary_content == "收藏的回應（DOM 截斷版）"


def test_focal_not_in_json_falls_back_to_heuristic() -> None:
    blob = _blob([_item("OTHER1", "someone", "無關內容")])
    enriched = _enricher(PageSnapshot(body_text="", embedded_json_blobs=[blob])).enrich(_source())
    assert enriched.reply_fetch_status in {"fetched_fallback", "no_author_replies"}


def test_saved_reply_self_thread_goes_to_author_replies() -> None:
    blob = _blob(
        [
            _item("ROOT01", "original_poster", "母帖全文"),
            _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
            _item("SELF1", "replier_b", "收藏回應的自串第二段", reply_to="replier_b"),
        ],
    )
    enriched = _enricher(PageSnapshot(body_text="", embedded_json_blobs=[blob])).enrich(_source())

    assert enriched.saved_kind == "reply"
    assert enriched.author_replies == ["收藏回應的自串第二段"]
    assert enriched.reply_threads == []
    assert "收藏回應的自串第二段" in enriched.combined_content
