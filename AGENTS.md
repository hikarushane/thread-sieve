# crawl-the-threads — Codex instructions

End-to-end automation for the **scrape Threads bookmarks → classify → unsave AI posts → produce markdown notes** pipeline. Two coupled layers: `userscripts/threads-scriber-auto.user.js` (browser, Tampermonkey) and `scripts/*.py` (Python pipeline). Tests live in `tests/` (pure Python).

## Debugging bugs

Invoke `/debug-loop <bug description>` for any bug across the userscript or Python pipeline. The slash command runs the Superpowers chain (`systematic-debugging` → `test-driven-development` → `verification-before-completion`) and enforces:
- failing regression test BEFORE production code change,
- one hypothesis at a time,
- fresh verification-command output before any "fixed" claim,
- stop-and-ask after three distinct failed fix attempts.

See `DEBUGGING.md` (English) or `DEBUGGING.zh-TW.md` (繁體中文) for the operator handbook.

## Testing

```
pytest tests/
```

Run from project root with venv active (`.\.venv\Scripts\Activate.ps1`). Add regression tests next to the existing files:
- `tests/test_classify_to_scribe_ai.py`
- `tests/test_watch_pipeline.py`
- `tests/test_pipeline_output.py`

## Userscript deploy

After editing `userscripts/threads-scriber-auto.user.js`:

```
python scripts/push_userscript.py --probe
```

Pushes into the open Tampermonkey editor tab (auto-detected by title), clicks the active script's Save button, reloads `/saved`, then runs `agent_driver.py probe`. Never paste manually.

## Smoke check (read-only)

```
python scripts/agent_driver.py probe
```

Confirms the userscript panel, `SCRIPT_VERSION`, and FS Access handles are bound.

## JS-only bugs

Pure Python pytest cannot verify DOM / userscript internals. For JS-only bugs the regression proof is `agent_driver.py probe` + a documented manual repro — do not fake a passing pytest.
