"""Host adapter regression: with window.__threadSieveHost present the userscript
must not touch File System Access pickers or window.confirm, and must report
status through the host. Inlines the synthetic /saved fixture also used by
test_userscript_unsave_flow.py (that file is an untracked developer fixture,
not committed to git, so it cannot be imported here). Per-post worker tabs
are stubbed by a permalink route that answers the localStorage task directly.
Skips when chromium is unavailable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

# Inlined verbatim from tests/test_userscript_unsave_flow.py (that file is an
# untracked fixture in the developer's checkout, not committed to git, so it
# cannot be imported from here on a clean clone).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
USERSCRIPT_PATH = PROJECT_ROOT / "userscripts" / "threads-scriber-auto.user.js"
PANEL_ID = "threads-saved-export-panel"
SAVED_URL = "https://www.threads.com/saved"

POST_IDS = ["TESTAAA111", "TESTBBB222", "TESTCCC333", "TESTDDD444"]


def build_fixture_html(post_ids):
    articles = "".join(
        f"""
      <article>
        <div><a href="/@tester">tester</a></div>
        <a href="/@tester/post/{pid}"><time datetime="2026-07-01T00:00:00.000Z">07-01</time></a>
        <div>這是一篇測試貼文內容，講 AI 工具與自動化流程，字數需要超過二十個字元才算有效。({pid})</div>
        <div role="button" class="more-btn" data-pid="{pid}"><svg aria-label="更多" width="20" height="20" viewBox="0 0 20 20"></svg></div>
      </article>"""
        for pid in post_ids
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>我的珍藏 • Threads</title>
<style>
  article {{ display: block; min-height: 70px; border: 1px solid #ccc; margin: 4px; padding: 4px; }}
  .more-btn {{ display: inline-block; width: 24px; height: 24px; }}
  .fake-menu {{ position: fixed; top: 40px; left: 40px; background: #fff; border: 1px solid #999; z-index: 99; }}
  .fake-menu [role="menuitem"] {{ display: block; width: 100px; height: 24px; }}
</style>
</head>
<body>
<main>{articles}</main>
<script>
  window.__unsaved = [];
  document.addEventListener("click", (ev) => {{
    const btn = ev.target.closest(".more-btn");
    if (btn) {{
      document.querySelectorAll(".fake-menu").forEach((m) => m.remove());
      const menu = document.createElement("div");
      menu.className = "fake-menu";
      menu.dataset.pid = btn.dataset.pid;
      menu.innerHTML = '<div role="menuitem">取消儲存</div>';
      document.body.appendChild(menu);
      ev.stopPropagation();
      return;
    }}
    const item = ev.target.closest('[role="menuitem"]');
    if (item) {{
      const pid = item.closest(".fake-menu").dataset.pid;
      window.__unsaved.push(pid);
      document.querySelectorAll("article").forEach((a) => {{
        if (a.querySelector('a[href*="/post/' + pid + '"]')) a.remove();
      }});
      item.closest(".fake-menu").remove();
      ev.stopPropagation();
      return;
    }}
    document.querySelectorAll(".fake-menu").forEach((m) => m.remove());
  }}, true);
</script>
</body></html>"""


def make_unsave_payload(post_ids):
    return {
        "generatedAt": "2026-07-18T00:00:00+00:00",
        "backend": "test",
        "items": [
            {
                "postId": pid,
                "postUrl": f"https://www.threads.com/@tester/post/{pid}",
                "decision": "ai",
                "confidence": 1.0,
                "reason": "test fixture",
            }
            for pid in post_ids
        ],
    }


TASK_KEY = "threadsSieveUrlUnsaveTask"
RESULT_KEY = "threadsSieveUrlUnsaveResult"

# Replaces the real per-post worker: read the task the main page wrote, answer it.
WORKER_STUB_HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
  const task = JSON.parse(localStorage.getItem("{TASK_KEY}") || "null");
  if (task) {{
    localStorage.setItem("{RESULT_KEY}", JSON.stringify({{
      nonce: task.nonce, key: task.key, outcome: "unsaved", detail: "stub-worker"
    }}));
  }}
</script></body></html>"""

HOST_INIT = """
(payload) => {
  window.__hostEvents = [];
  window.__savedCatch = null;
  window.__threadSieveHost = {
    saveCatch: async (text) => { window.__savedCatch = text; },
    getUnsaveList: async () => payload.items,
    reportStatus: (event) => { window.__hostEvents.push(event); },
  };
  window.confirm = () => { throw new Error("confirm must not be called in host mode"); };
  window.showOpenFilePicker = async () => { throw new Error("picker must not be called in host mode"); };
  window.showSaveFilePicker = async () => { throw new Error("picker must not be called in host mode"); };
}
"""


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except playwright_sync.Error as error:
            pytest.skip(f"chromium unavailable: {error}")
        yield browser
        browser.close()


def _open(browser):
    context = browser.new_context()
    context.route(
        f"{SAVED_URL}*",
        lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=build_fixture_html(POST_IDS)
        ),
    )
    context.route(
        "https://www.threads.com/@tester/post/*",
        lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=WORKER_STUB_HTML
        ),
    )
    page = context.new_page()
    page.add_init_script(f"({HOST_INIT})({json.dumps(make_unsave_payload(POST_IDS))})")
    page.goto(SAVED_URL)
    page.add_script_tag(path=str(USERSCRIPT_PATH))
    page.wait_for_selector(f"#{PANEL_ID}-unsave-run")
    return page


def test_autosave_button_uses_host_without_picker(browser) -> None:
    page = _open(browser)
    page.click(f"#{PANEL_ID}-autosave")
    page.wait_for_function(
        f"() => document.getElementById('{PANEL_ID}-meta').textContent.includes('catch.json')"
    )
    kinds = page.evaluate("() => window.__hostEvents.map((e) => e.kind)")
    assert "autosave_ready" in kinds
    assert page.evaluate(f"() => document.getElementById('{PANEL_ID}-error').textContent") == ""


def test_unsave_run_uses_host_list_and_reports_results(browser) -> None:
    page = _open(browser)
    page.click(f"#{PANEL_ID}-unsave-run")
    page.wait_for_function(
        "() => window.__hostEvents.some((e) => e.kind === 'unsave_finished')",
        timeout=60000,
    )
    events = page.evaluate("() => window.__hostEvents")
    item_events = [e for e in events if e["kind"] == "unsave_item"]
    assert sorted(e["data"]["key"] for e in item_events) == sorted(POST_IDS)
    assert all(e["data"]["outcome"] == "unsaved" for e in item_events)
    finished = [e for e in events if e["kind"] == "unsave_finished"][-1]
    assert finished["data"]["unsaved"] == len(POST_IDS)
    assert finished["data"]["stopReason"] == "completed"
    assert page.evaluate(f"() => document.getElementById('{PANEL_ID}-error').textContent") == ""
