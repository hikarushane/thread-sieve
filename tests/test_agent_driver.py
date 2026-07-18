import json
from pathlib import Path

import pytest

import scripts.agent_driver as mod


def make_probe_result(**overrides: object) -> dict:
    result: dict = {
        "url": "https://www.threads.com/saved",
        "scriptVersion": mod.EXPECTED_VERSION,
        "autoSaveBound": True,
        "agentBridge": True,
        "buttons": {key: True for key in mod.PROBE_BUTTON_KEYS},
    }
    result.update(overrides)
    return result


def test_evaluate_probe_result_ok() -> None:
    assert mod.evaluate_probe_result(make_probe_result()) == []


def test_evaluate_probe_result_panel_missing_short_circuits() -> None:
    assert mod.evaluate_probe_result({"error": "panel missing"}) == ["panel missing"]


def test_evaluate_probe_result_flags_version_autosave_bridge_and_buttons() -> None:
    result = make_probe_result(
        scriptVersion="0.4.1",
        autoSaveBound=False,
        agentBridge=False,
        buttons={**{key: True for key in mod.PROBE_BUTTON_KEYS}, "unsave-run": False},
    )
    problems = mod.evaluate_probe_result(result)
    assert f"scriptVersion=0.4.1 expected {mod.EXPECTED_VERSION}" in problems
    assert "autosave (catch.json) not bound" in problems
    assert mod.AGENT_BRIDGE_MISSING_HINT in problems
    assert any("unsave-run" in problem for problem in problems)


def test_build_agent_unsave_expr_embeds_payload_as_json_string() -> None:
    payload = json.dumps({"items": [{"postId": "abc", "reason": '含"引號"與中文'}]}, ensure_ascii=False)
    expr = mod.build_agent_unsave_expr(payload)
    assert "window.ThreadSieveAgent" in expr
    assert json.dumps(payload) in expr
    assert json.dumps(mod.AGENT_BRIDGE_MISSING_HINT) in expr


def test_run_agent_bridge_unsave_rejects_oversized_payload() -> None:
    payload = "x" * (mod.MAX_UNSAVE_PAYLOAD_CHARS + 1)
    with pytest.raises(RuntimeError, match="too large"):
        mod.run_agent_bridge_unsave(0, payload)


def test_confirmation_gate_reads_fresh_payload_and_calls_bridge(tmp_path: Path, monkeypatch) -> None:
    catch_path = tmp_path / "catch.json"
    unsave_path = tmp_path / "unsave.json"
    catch_path.write_text(
        json.dumps([{"postId": "p1", "authorName": "Alice", "contentText": "First sentence. More."}]),
        encoding="utf-8",
    )
    unsave_payload = {"generatedAt": "2026-07-18T00:00:00Z", "items": [{"postId": "p1"}]}
    unsave_path.write_text(json.dumps(unsave_payload), encoding="utf-8")

    calls: list[tuple[int, str]] = []

    def fake_bridge(tab_index: int, payload_text: str) -> dict:
        calls.append((tab_index, payload_text))
        return {"ok": True, "verified": 1, "attempted": 0, "failed": 0, "remainingSelected": 0}

    monkeypatch.setattr(mod, "run_agent_bridge_unsave", fake_bridge)

    rc = mod.run_unsave_confirmation_gate(
        tab_index=3,
        catch_path=catch_path,
        unsave_path=unsave_path,
        previous_generated_at="",
        timeout_seconds=5.0,
        input_fn=lambda _prompt: "y",
    )

    assert rc == 0
    assert calls == [(3, unsave_path.read_text(encoding="utf-8"))]


def test_confirmation_gate_declined_leaves_browser_untouched(tmp_path: Path, monkeypatch) -> None:
    catch_path = tmp_path / "catch.json"
    unsave_path = tmp_path / "unsave.json"
    catch_path.write_text("[]", encoding="utf-8")
    unsave_path.write_text(
        json.dumps({"generatedAt": "2026-07-18T00:00:00Z", "items": [{"postId": "p1", "authorName": "A", "contentText": "hi"}]}),
        encoding="utf-8",
    )

    def fail_bridge(tab_index: int, payload_text: str) -> dict:
        raise AssertionError("bridge must not run when the gate is declined")

    monkeypatch.setattr(mod, "run_agent_bridge_unsave", fail_bridge)

    rc = mod.run_unsave_confirmation_gate(
        tab_index=0,
        catch_path=catch_path,
        unsave_path=unsave_path,
        previous_generated_at="",
        timeout_seconds=5.0,
        input_fn=lambda _prompt: "n",
    )
    assert rc == 0
