"""Playwright coverage for note_generator/services/dom_thread_extract.js against
synthetic HTML that mirrors the DOM facts recorded in that file's header
comment (observed on www.threads.com post pages, 2026-09-18). Skips when
chromium is unavailable."""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = PROJECT_ROOT / "note_generator" / "services" / "dom_thread_extract.js"


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except playwright_sync.Error as error:
            pytest.skip(f"chromium unavailable: {error}")
        yield browser
        browser.close()


def _post_html(code: str, handle: str, body_lines: list[str], rel_time: str = "2h", likes: str = "12") -> str:
    body_spans = "\n".join(f'<span dir="auto">{line}</span>' for line in body_lines)
    return f"""
      <div data-pressable-container id="c-{code}">
        <a href="/@{handle}/post/{code}"><time datetime="2026-09-18T00:00:00.000Z">{rel_time}</time></a>
        <div role="button"><svg><title>更多</title></svg></div>
        <span dir="auto">{handle}</span>
        <span dir="auto">{rel_time}</span>
        {body_spans}
        <span dir="auto">{likes}</span>
      </div>
    """


def _cookie_dialog_html() -> str:
    return """
      <div data-pressable-container id="c-cookie">
        <span dir="auto">Cookies 說明文字，這裡沒有 time 連結。</span>
        <button>Accept</button>
      </div>
    """


MAIN_THREAD_HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
{_cookie_dialog_html()}
<main>
  <div class="thread-section">
    <div class="post-list">
      {_post_html("T1FOCAL", "author_focal", ["主貼文本文，這是收藏的原帖。"])}
      <div class="replies">
        {_post_html("T1R1", "commenter_x", ["第一組唯一一則回覆。"])}
        <div class="reply-chain">
          {_post_html("T1R2", "commenter_y", ["第二組第一則。"])}
          {_post_html("T1R3", "commenter_z", ["第二組第二則，同一條鏈。"])}
        </div>
      </div>
    </div>
  </div>
  <div class="related-section">
    <span dir="auto">相關串文</span>
    {_post_html("OLD1", "someone_else", ["較舊的相關貼文一。"])}
    {_post_html("OLD2", "another_person", ["較舊的相關貼文二。"])}
  </div>
</main>
</body></html>"""


SAVED_REPLY_HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
{_cookie_dialog_html()}
<main>
  <div class="thread-section">
    <div class="post-list">
      {_post_html("ROOT01", "original_poster", ["母帖全文。"])}
      {_post_html("MID01", "replier_a", ["上層的中間回覆。"])}
      {_post_html("T2FOCAL", "replier_b", ["收藏的這則回覆。"])}
    </div>
  </div>
  <div class="related-section">
    <span dir="auto">Related threads</span>
    {_post_html("OLD3", "someone_else", ["較舊的相關貼文三。"])}
  </div>
</main>
</body></html>"""


def _extract(page, focal_code: str) -> dict:
    js = JS_PATH.read_text(encoding="utf-8")
    return page.evaluate(f"({js})({focal_code!r})")


def test_extracts_focal_and_grouped_replies_excluding_related_and_cookie(browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.set_content(MAIN_THREAD_HTML)

    result = _extract(page, "T1FOCAL")

    assert result["focalCode"] == "T1FOCAL"
    codes = [p["code"] for p in result["posts"]]
    assert codes == ["T1FOCAL", "T1R1", "T1R2", "T1R3"]

    roles = {p["code"]: p["role"] for p in result["posts"]}
    assert roles["T1FOCAL"] == "focal"
    assert roles["T1R1"] == "reply"
    assert roles["T1R2"] == "reply"
    assert roles["T1R3"] == "reply"

    groups = {p["code"]: p["group"] for p in result["posts"]}
    assert groups["T1FOCAL"] == 0
    assert groups["T1R1"] == 1
    assert groups["T1R2"] == groups["T1R3"]
    assert groups["T1R2"] != groups["T1R1"]

    # Related threads and the cookie dialog must not leak into posts.
    assert "OLD1" not in codes
    assert "OLD2" not in codes
    assert "c-cookie" not in codes

    focal_post = next(p for p in result["posts"] if p["code"] == "T1FOCAL")
    assert "author_focal" not in focal_post["text"]
    assert "2h" not in focal_post["text"]
    assert "12" not in focal_post["text"]
    assert "主貼文本文" in focal_post["text"]

    context.close()


def test_extracts_ancestor_chain_for_saved_reply(browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.set_content(SAVED_REPLY_HTML)

    result = _extract(page, "T2FOCAL")

    codes = [p["code"] for p in result["posts"]]
    assert codes == ["ROOT01", "MID01", "T2FOCAL"]

    roles = {p["code"]: p["role"] for p in result["posts"]}
    assert roles["ROOT01"] == "ancestor"
    assert roles["MID01"] == "ancestor"
    assert roles["T2FOCAL"] == "focal"

    assert "OLD3" not in codes

    context.close()


def test_missing_focal_returns_empty_posts(browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.set_content(MAIN_THREAD_HTML)

    result = _extract(page, "NO_SUCH_CODE")

    assert result == {"focalCode": "NO_SUCH_CODE", "posts": []}

    context.close()
