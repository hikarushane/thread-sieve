from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
