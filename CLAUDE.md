# ThreadSieve — Claude Code instructions

End-to-end automation for the **scrape Threads bookmarks → classify → unsave AI posts → produce markdown notes** pipeline. Two coupled layers: `userscripts/threads-scriber-auto.user.js` (browser, Tampermonkey) and `scripts/*.py` (Python pipeline). Tests live in `tests/` (pure Python).

## Debugging bugs

Invoke `/debug-loop <bug description>` for any bug across the userscript or Python pipeline. The slash command runs the Superpowers chain (`systematic-debugging` → `test-driven-development` → `verification-before-completion`) and enforces:
- failing regression test BEFORE production code change,
- one hypothesis at a time,
- fresh verification-command output before any "fixed" claim,
- stop-and-ask after three distinct failed fix attempts.

See `DEBUGGING.md` (English) or `DEBUGGING.zh-TW.md` (繁體中文) for the operator handbook.

## README consistency gate

If a code change modifies user-visible behavior, setup, deployment, verification, or agent workflow in a way that differs from the current `README.md`, do not edit `README.md` immediately. First tell the user what README change is needed and propose a short plan; edit `README.md` only after the user confirms.

## Open-source and personalization gate

Before any change, consider whether it keeps the repo safe and useful for a future public release:
- Do not hardcode personal categories, fandom names, private labels, local absolute paths, account handles, bookmark URLs, or workflow preferences in Python, userscript code, tests, docs, or checked-in examples.
- Keep project behavior generic by default. Put user-specific categories, prompt hints, auto-unsave categories, keyword overrides, paths, and local tool locations in `config.json`, `.env`, or another documented local config surface.
- Prefer config-driven extension points over special-case code. If a rule is useful only for one user's taxonomy, implement it as a generic config mechanism and keep the private values out of source.
- Tests should use neutral sample categories and placeholder data unless the test is explicitly about a public, documented fixture.
- When a requested fix seems personal, preserve the fix as a reusable capability and explain where the user's private values should live.

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

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
