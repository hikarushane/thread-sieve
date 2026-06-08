---
description: Reproduce, regress, fix, and verify a bug across the userscript + Python pipeline using Superpowers discipline.
argument-hint: <bug description>
---

Bug: $ARGUMENTS

Use Superpowers skills for this bugfix.

First invoke and follow:
- superpowers:using-superpowers
- superpowers:systematic-debugging
- superpowers:test-driven-development
- superpowers:verification-before-completion

## Goal

Debug this bug end-to-end. Reproduce the failure, identify the root cause before changing code, add a minimal failing regression test, verify the test fails for the expected reason, implement the smallest fix, then run the targeted test and the relevant full test suite.

## Loop behavior

If tests fail after a fix, do not stack random fixes. Re-enter systematic debugging with the new evidence:
1. Read the full error output.
2. State the current hypothesis.
3. Test one hypothesis at a time.
4. Make one minimal change.
5. Re-run the relevant tests.

Continue until:
- the regression test passes,
- the relevant suite passes,
- and verification-before-completion has fresh command output proving it.

## Stop and ask before continuing if

- the same issue survives three distinct fix attempts,
- the root cause points to a larger architecture problem,
- a dependency or environment issue blocks reliable verification,
- or the correct behavior is ambiguous.

## Constraints

- No production-code changes before a failing test unless only adding diagnostics to find root cause.
- No broad refactors while fixing the bug.
- Do not claim success without running the verification commands and reading their output.
- Preserve unrelated user changes in the worktree.

## Project-specific deployment

This project has two coupled layers — a Tampermonkey userscript and a Python pipeline. Use the right deploy step for each:

- **Edited `userscripts/threads-scriber-auto.user.js`**:
  Run `python scripts/push_userscript.py --probe`. This pushes the file into the open Tampermonkey editor tab (auto-detected by title), clicks the active script's Save button, reloads the `/saved` tab, then runs `agent_driver.py probe` for a readiness check.

- **Edited `scripts/*.py`**:
  Rerun `pytest tests/` from the project root with the venv active.

- **Anytime smoke check**:
  `python scripts/agent_driver.py probe` — confirms panel + `SCRIPT_VERSION` + autosave/handle bindings.

## JS-only bugs — be honest about the test gap

Tests in `tests/` are pure Python and assert on file artifacts (`data/catch.json`, `data/unsave.json`) or pure Python modules. They cannot verify DOM scraping, FS Access API handles, or panel UI internals that live entirely in the userscript.

For JS-only bugs:
- The regression "test" is `agent_driver.py probe` (structural) + a documented manual reproduction step.
- Do NOT write a fake passing pytest to claim victory.
- The verification-before-completion gate must read fresh `probe` output and confirm the manual repro no longer triggers.

## Preflight before starting the loop

- Chrome running with `--remote-debugging-port=9222` (see `README.md` section 0.C)
- `https://www.threads.com/saved` tab open
- Tampermonkey dashboard → "Threads Scriber (Auto, crawl-the-threads)" editor tab open (the helper looks for it by title)
- venv active; `CHROME_WS_PATH` set in `.env`

If any preflight fails, surface it immediately — do not proceed into the loop with broken infrastructure.
