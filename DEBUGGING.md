# Debugging

Reference for the `/debug-loop` Claude Code slash command and the userscript push helper. Operator-friendly handbook in 繁體中文: see [`DEBUGGING.zh-TW.md`](DEBUGGING.zh-TW.md).

## Overview

`/debug-loop <bug>` runs a Superpowers-driven bugfix protocol that chains:

- `superpowers:systematic-debugging` — root cause before any fix
- `superpowers:test-driven-development` — failing regression test before production code
- `superpowers:verification-before-completion` — fresh command output before any "done" claim

Stop condition: three distinct failed fix attempts → Claude halts and asks before continuing.

## Prerequisites

- Chrome launched with `--remote-debugging-port=9222` (README section 0.C)
- Threads `/saved` tab open: `https://www.threads.com/saved`
- Tampermonkey dashboard → click into the **ThreadSieve (Auto)** script (the editor tab is auto-detected by title; it must be open)
- Virtual env active: `.\.venv\Scripts\Activate.ps1`
- `.env` populated, and `config.json` has `paths.chrome-ws-cli`

## Usage

In Claude Code, from any session:

```
/debug-loop watcher misses catch.json updates under 500ms
```

Claude will:
1. Reproduce the failure.
2. Form one hypothesis, prove it minimally.
3. Write a failing regression test.
4. Apply the smallest fix.
5. Re-run the targeted test, then the suite.
6. If the userscript was edited, run `scripts/push_userscript.py --probe` to deploy + verify.
7. Show fresh command output as proof before closing the loop.

## Command cheatsheet

| Command | What it does |
| --- | --- |
| `python scripts/push_userscript.py` | Push current `userscripts/threads-scriber-auto.user.js` into the Tampermonkey editor, click Save, reload `/saved`. |
| `python scripts/push_userscript.py --probe` | Same as above, then run `agent_driver.py probe`. **Use after every userscript edit.** |
| `python scripts/push_userscript.py --no-reload` | Push + save only; do not reload `/saved`. |
| `python scripts/agent_driver.py probe` | Read-only check: panel present, `SCRIPT_VERSION` matches, FS Access handles bound. |
| `pytest tests/` | Run the full Python test suite. |

## Troubleshooting

| Exit / symptom | Cause | Fix |
| --- | --- | --- |
| `push_userscript.py` exits 2 — "no Tampermonkey editor tab" | Editor tab not open | Open Tampermonkey dashboard, click into the ThreadSieve (Auto) script |
| `push_userscript.py` exits 2 — chrome-ws CLI path missing | `config.json` path missing or empty | Set `paths.chrome-ws-cli` (see README section 0.B) |
| `push_userscript.py` exits 3 — "save failed" | Tampermonkey UI changed; Save button selector drifted | Inspect via `chrome-ws eval <tab> "[...document.querySelectorAll('button[title]')].map(b=>b.outerHTML)"`; update title regex / id pattern in `click_save()` |
| `push_userscript.py` exits 4 — "reload /saved failed" | `/saved` tab closed or chrome-ws lost connection | Reopen `https://www.threads.com/saved`; verify Chrome is on port 9222 |
| `probe` reports `panel missing` after a push | Userscript has a syntax error | Open Tampermonkey console (Tampermonkey icon → Dashboard → script → Console); fix the error and re-push |
| `probe` reports `scriptVersion=...` mismatch | `SCRIPT_VERSION` constant out of sync with `@version` | Bump both in `userscripts/threads-scriber-auto.user.js` (or `scripts/_rebuild_userscript.py`) |

## When NOT to use `/debug-loop`

The loop is built for bugs. Skip it for:
- Documentation-only changes
- Pure config edits (`config.json`, `.env`)
- New features (still use TDD, but the stop-after-3 protocol is overkill)

## JS-only bug honesty

Pytest cannot exercise DOM scraping, Tampermonkey GM APIs, or FS Access handles. For bugs that live entirely in the userscript:

- The "regression test" is `agent_driver.py probe` + a documented manual repro step.
- Do NOT write a fake Python test that passes vacuously.
- The verification-before-completion gate must read fresh probe output and confirm the manual repro no longer triggers.
