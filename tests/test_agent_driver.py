from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_driver as mod  # noqa: E402


def test_scrape_clears_existing_panel_results_before_start(monkeypatch):
    clicks: list[str] = []

    monkeypatch.setattr(mod, "find_saved_tab_index", lambda: 0)
    monkeypatch.setattr(mod, "chrome_eval", lambda _idx, _expr: "2026-05-15")
    monkeypatch.setattr(mod, "chrome_click", lambda _idx, selector: clicks.append(selector))

    assert mod.cmd_scrape(wait_seconds=0, cutoff="2026-05-15") == 0

    assert clicks == [
        "#threads-saved-export-panel-clear",
        "#threads-saved-export-panel-start",
    ]


def test_scrape_status_poll_retries_after_chrome_eval_timeout(monkeypatch, capsys):
    eval_results = [
        "2026-05-15",
        subprocess.TimeoutExpired(["node", "chrome-ws", "eval"], timeout=30.0),
        {"status": "完成", "count": 3},
    ]

    def fake_chrome_eval(_idx: int, _expr: str):
        result = eval_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    times = iter([0.0, 0.0, 1.0])

    monkeypatch.setattr(mod, "find_saved_tab_index", lambda: 0)
    monkeypatch.setattr(mod, "chrome_eval", fake_chrome_eval)
    monkeypatch.setattr(mod, "chrome_click", lambda _idx, _selector: None)
    monkeypatch.setattr(mod.time, "time", lambda: next(times))
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    assert mod.cmd_scrape(wait_seconds=10, cutoff="2026-05-15") == 0

    captured = capsys.readouterr()
    assert "WARN: status poll timed out; retrying" in captured.err


def test_probe_allows_closed_auto_sync_panel_when_handle_is_bound(monkeypatch, capsys):
    monkeypatch.setattr(mod, "find_saved_tab_index", lambda: 0)
    monkeypatch.setattr(
        mod,
        "chrome_eval",
        lambda _idx, _expr: {
            "url": "https://www.threads.com/saved",
            "scriptVersion": mod.EXPECTED_VERSION,
            "autoSaveBound": True,
            "autoPanelPresent": False,
            "autoSyncBound": True,
            "autoStatus": "handle: unsave.json · last seen: 2026-05-23T00:00:00.000Z",
            "buttons": {
                "start": True,
                "load-ai": True,
                "apply-ai": True,
                "select-high": True,
                "unsave-selected": True,
                "autosave": True,
            },
        },
    )

    assert mod.cmd_probe() == 0
    captured = capsys.readouterr()
    assert "OK: panel ready for agent-driven scrape" in captured.err


def test_first_sentence_stops_at_sentence_punctuation():
    assert mod.first_sentence("第一句。第二句\n第三句") == "第一句。"
    assert mod.first_sentence("First sentence! Second sentence.") == "First sentence!"
    assert mod.first_sentence("沒有標點的第一行\n第二行") == "沒有標點的第一行 第二行"
    assert mod.first_sentence("") == ""


def test_build_unsave_preview_lines_joins_items_to_catch_posts():
    catch_posts = [
        {
            "postId": "p1",
            "authorName": "Alice",
            "authorHandle": "@alice",
            "contentText": "第一句。第二句",
        },
        {
            "postId": "p2",
            "authorName": "",
            "authorHandle": "@bob",
            "contentText": "No punctuation first line\nsecond line",
        },
    ]
    unsave_payload = {
        "items": [
            {"postId": "p1"},
            {"postId": "p2"},
            {"postId": "missing"},
        ]
    }

    assert mod.build_unsave_preview_lines(catch_posts, unsave_payload) == [
        "作者:Alice| 貼文:第一句。",
        "作者:@bob| 貼文:No punctuation first line second line",
        "作者:(unknown)| 貼文:(post not found in catch.json)",
    ]


def test_ask_confirmation_accepts_only_lowercase_or_uppercase_y():
    assert mod.ask_confirmation(lambda _prompt: "y") is True
    assert mod.ask_confirmation(lambda _prompt: "Y") is True
    assert mod.ask_confirmation(lambda _prompt: "n") is False
    assert mod.ask_confirmation(lambda _prompt: "") is False


def test_ask_confirmation_treats_eof_as_decline():
    def raise_eof(_prompt: str) -> str:
        raise EOFError

    assert mod.ask_confirmation(raise_eof) is False


def test_wait_for_unsave_payload_returns_new_generated_at(tmp_path, monkeypatch):
    unsave = tmp_path / "unsave.json"
    unsave.write_text('{"generatedAt":"old","items":[]}', encoding="utf-8")
    sleeps: list[float] = []
    times = iter([0.0, 0.1])

    monkeypatch.setattr(mod.time, "time", lambda: next(times))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    unsave.write_text('{"generatedAt":"new","items":[{"postId":"p1"}]}', encoding="utf-8")

    payload = mod.wait_for_unsave_payload(
        unsave_path=unsave,
        previous_generated_at="old",
        timeout_seconds=5,
        poll_seconds=0.1,
    )

    assert payload["generatedAt"] == "new"


def test_confirm_unsave_gate_decline_does_not_run_browser_unsave(tmp_path, monkeypatch, capsys):
    catch = tmp_path / "catch.json"
    unsave = tmp_path / "unsave.json"
    catch.write_text(
        '[{"postId":"p1","authorName":"Alice","authorHandle":"@alice","contentText":"第一句。第二句"}]',
        encoding="utf-8",
    )
    unsave.write_text('{"generatedAt":"new","items":[{"postId":"p1"}]}', encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        mod,
        "wait_for_unsave_payload",
        lambda **_kwargs: mod.load_json_file(unsave),
    )
    monkeypatch.setattr(mod, "run_confirmed_browser_unsave", lambda _tab_index: calls.append("run"))

    rc = mod.run_unsave_confirmation_gate(
        tab_index=0,
        catch_path=catch,
        unsave_path=unsave,
        previous_generated_at="old",
        timeout_seconds=5,
        input_fn=lambda _prompt: "n",
    )

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "即將取消儲存以下貼文:" in out
    assert "作者:Alice| 貼文:第一句。" in out
    assert "已取消執行；unsave.json 已保留，browser auto-unsave 維持關閉。" in out


def test_confirm_unsave_gate_accept_runs_browser_unsave(tmp_path, monkeypatch):
    catch = tmp_path / "catch.json"
    unsave = tmp_path / "unsave.json"
    catch.write_text('[{"postId":"p1","authorHandle":"@alice","contentText":"第一句。"}]', encoding="utf-8")
    unsave.write_text('{"generatedAt":"new","items":[{"postId":"p1"}]}', encoding="utf-8")
    calls: list[int] = []

    monkeypatch.setattr(
        mod,
        "wait_for_unsave_payload",
        lambda **_kwargs: mod.load_json_file(unsave),
    )
    monkeypatch.setattr(mod, "run_confirmed_browser_unsave", lambda tab_index: calls.append(tab_index) or {"ok": True})

    rc = mod.run_unsave_confirmation_gate(
        tab_index=7,
        catch_path=catch,
        unsave_path=unsave,
        previous_generated_at="old",
        timeout_seconds=5,
        input_fn=lambda _prompt: "y",
    )

    assert rc == 0
    assert calls == [7]


def test_coerce_chrome_json_parses_string_into_dict():
    result = mod._coerce_chrome_json('{"ok":true,"value":1}')
    assert result == {"ok": True, "value": 1}


def test_coerce_chrome_json_returns_dict_passthrough():
    payload = {"ok": False, "error": "missing"}
    assert mod._coerce_chrome_json(payload) is payload


def test_coerce_chrome_json_raises_on_non_object_result():
    with pytest.raises(RuntimeError, match="expected object result from browser"):
        mod._coerce_chrome_json([1, 2, 3])
    with pytest.raises(RuntimeError, match="expected object result from browser"):
        mod._coerce_chrome_json(None)


def test_set_browser_auto_unsave_raises_when_api_missing(monkeypatch):
    monkeypatch.setattr(
        mod,
        "chrome_eval",
        lambda _idx, _expr: '{"ok":false,"error":"ThreadSieveAutoAiSync API missing"}',
    )
    with pytest.raises(RuntimeError, match="ThreadSieveAutoAiSync API missing"):
        mod.set_browser_auto_unsave(0, False)


def test_set_browser_auto_unsave_returns_success_payload(monkeypatch):
    monkeypatch.setattr(
        mod,
        "chrome_eval",
        lambda _idx, _expr: '{"ok":true,"state":{"autoUnsave":false,"verified":0}}',
    )
    result = mod.set_browser_auto_unsave(0, False)
    assert result == {"ok": True, "state": {"autoUnsave": False, "verified": 0}}


def test_run_confirmed_browser_unsave_raises_when_force_load_fails(monkeypatch):
    monkeypatch.setattr(
        mod,
        "chrome_eval",
        lambda _idx, _expr: '{"ok":false,"error":"forceLoad failed","loaded":{"ok":false}}',
    )
    with pytest.raises(RuntimeError, match="forceLoad failed"):
        mod.run_confirmed_browser_unsave(0)


def test_wait_for_unsave_payload_retries_until_generated_at_changes(tmp_path, monkeypatch):
    unsave = tmp_path / "unsave.json"
    sleeps: list[float] = []

    states = iter([
        FileNotFoundError(),
        '{"generatedAt":"old","items":[]}',
        '{"generatedAt":"new","items":[{"postId":"p1"}]}',
    ])

    def fake_load_json_file(path):
        nxt = next(states)
        if isinstance(nxt, BaseException):
            raise nxt
        return mod.json.loads(nxt)

    monkeypatch.setattr(mod, "load_json_file", fake_load_json_file)
    times = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(mod.time, "time", lambda: next(times))
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = mod.wait_for_unsave_payload(
        unsave_path=unsave,
        previous_generated_at="old",
        timeout_seconds=5,
        poll_seconds=0.1,
    )

    assert payload["generatedAt"] == "new"
    assert sleeps == [0.1, 0.1]


def test_wait_for_unsave_payload_raises_timeout_when_deadline_passes(tmp_path, monkeypatch):
    unsave = tmp_path / "unsave.json"
    monkeypatch.setattr(
        mod,
        "load_json_file",
        lambda _path: {"generatedAt": "old", "items": []},
    )
    times = iter([0.0, 0.1, 0.2, 5.1])
    monkeypatch.setattr(mod.time, "time", lambda: next(times))
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="unsave.json did not update within 5s"):
        mod.wait_for_unsave_payload(
            unsave_path=unsave,
            previous_generated_at="old",
            timeout_seconds=5,
            poll_seconds=0.1,
        )
