from __future__ import annotations

import json

from note_generator.services.thread_page_parser import parse_thread_page


def _item(code: str, username: str, text: str, reply_to: str | None = None) -> dict:
    info: dict = {"direct_reply_count": 0}
    if reply_to:
        info["reply_to_author"] = {"username": reply_to}
    return {
        "post": {
            "pk": f"pk-{code}",
            "code": code,
            "user": {"username": username},
            "caption": {"text": text},
            "text_post_app_info": info,
        }
    }


def _blob(*chains: list[dict]) -> str:
    edges = [{"node": {"thread_items": chain}} for chain in chains]
    return json.dumps({"require": [{"__bbox": {"result": {"data": {"data": {"edges": edges}}}}}]})


def test_three_level_ancestor_chain() -> None:
    blob = _blob([
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("MID01", "replier_a", "中間層", reply_to="original_poster"),
        _item("FOCAL01", "replier_b", "收藏的回應", reply_to="replier_a"),
    ])
    data = parse_thread_page([blob], "FOCAL01")
    assert data.focal is not None
    assert data.focal.code == "FOCAL01"
    assert [p.code for p in data.ancestor_chain] == ["ROOT01", "MID01"]
    assert data.ancestor_chain[0].author_handle == "original_poster"
    assert data.ancestor_chain[0].text == "母帖全文"
    assert data.reply_threads == []


def test_sibling_edges_become_reply_threads() -> None:
    blob = _blob(
        [
            _item("ROOT01", "original_poster", "母帖全文"),
            _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
        ],
        [
            _item("C1", "commenter_c", "路人問題", reply_to="original_poster"),
            _item("OPR1", "original_poster", "原作者回覆", reply_to="commenter_c"),
        ],
    )
    data = parse_thread_page([blob], "FOCAL01")
    assert [p.code for p in data.ancestor_chain] == ["ROOT01"]
    assert len(data.reply_threads) == 1
    assert [p.code for p in data.reply_threads[0]] == ["C1", "OPR1"]
    assert data.reply_threads[0][1].reply_to_handle == "commenter_c"


def test_trailing_items_after_focal_become_reply_thread() -> None:
    blob = _blob([
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
        _item("CHILD1", "commenter_c", "對收藏回應的回覆", reply_to="replier_b"),
    ])
    data = parse_thread_page([blob], "FOCAL01")
    assert [p.code for p in data.reply_threads[0]] == ["CHILD1"]


def test_focal_as_root_has_empty_chain() -> None:
    blob = _blob([_item("FOCAL01", "original_poster", "母帖全文")])
    data = parse_thread_page([blob], "FOCAL01")
    assert data.focal is not None
    assert data.ancestor_chain == []


def test_focal_not_found_returns_none() -> None:
    blob = _blob([_item("OTHER1", "someone", "無關內容")])
    data = parse_thread_page([blob], "FOCAL01")
    assert data.focal is None
    assert data.ancestor_chain == []
    assert data.reply_threads == []


def test_duplicate_chains_across_blobs_are_deduped() -> None:
    chain = [
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
    ]
    data = parse_thread_page([_blob(chain), _blob(chain)], "FOCAL01")
    assert data.reply_threads == []


def test_broken_json_and_missing_keys_are_skipped() -> None:
    good = _blob([_item("FOCAL01", "original_poster", "母帖全文")])
    data = parse_thread_page(["{not json", json.dumps({"edges": "not-a-list"}), good], "FOCAL01")
    assert data.focal is not None


def test_longer_duplicate_focal_chain_across_blobs_is_not_a_reply_thread() -> None:
    short = [
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
    ]
    longer = [
        _item("ROOT01", "original_poster", "母帖全文"),
        _item("FOCAL01", "replier_b", "收藏的回應", reply_to="original_poster"),
        _item("CHILD1", "commenter_c", "對收藏回應的回覆", reply_to="replier_b"),
    ]
    data = parse_thread_page([_blob(short), _blob(longer)], "FOCAL01")
    assert data.focal is not None
    assert [p.code for p in data.ancestor_chain] == ["ROOT01"]
    assert data.reply_threads == []


def test_items_without_code_or_user_are_dropped() -> None:
    blob = _blob([
        {"post": {"code": "", "user": {"username": "x"}, "caption": {"text": "no code"}}},
        _item("FOCAL01", "original_poster", "母帖全文"),
    ])
    data = parse_thread_page([blob], "FOCAL01")
    assert data.focal is not None
    assert data.ancestor_chain == []
