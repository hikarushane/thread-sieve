# ThreadSieve (full / power-user) — Claude Code instructions

Power-user branch. Two layers: `userscripts/threads-scriber-auto.user.js` (browser, Tampermonkey) and `scripts/*.py` (Python: classify + markdown + image OCR, plus the automation layer — `watch_pipeline.py` watcher, `agent_driver.py` / `push_userscript.py` via `superpowers-chrome` + Chrome `--remote-debugging-port=9222`, and the Chandra/vLLM OCR backend). Path 1 (double-click `run_classify.cmd` / `.command`) works without any of that.

## README consistency gate

If a code change modifies user-visible behavior, setup, or the single SOP in a way that differs from `README.md`, do not edit `README.md` immediately. First propose the change; edit only after the user confirms. Keep `README.md` and `README.en.md` in sync.

## Open-source and personalization gate

- No hardcoded personal categories, private labels, absolute paths, account handles, bookmark URLs in code, tests, docs, or examples.
- Put user-specific values in `config.json` / `.env`.
- Prefer config-driven extension points over special-case code.

## Testing

```
pytest tests/
```

Run from project root with venv active (`.\.venv\Scripts\Activate.ps1`). Note: `.gitignore` lists `tests/`, but the test files are tracked (added before the ignore rule) and SHOULD be committed — new test files need `git add -f tests/...`; verify with `git show --stat HEAD` that they made it into the commit.

## Branch scope (full)

This IS the branch for the automation layer: `agent_driver.py`, `push_userscript.py`, `watch_pipeline.py`, `classify_to_scribe_ai.py`, `superpowers-chrome` / `chrome-ws`, Chrome `--remote-debugging-port`, Chandra/vLLM OCR, and the `.claude` / `.codex` / `.antigravity` hooks all live here.

The lite guardrail applies to `main` (the default, end-user branch): never sync any of the above back to `main`. Code changes that belong on both branches land on `main` first, then get cherry-picked here (the two branches share file content but not commit SHAs — sync with cherry-pick, never merge).

Known divergence: the userscript here is the full-branch build (0.4.2) — lite's 0.4.1 plus the `window.ThreadSieveAgent` bridge block near the end of the file, which lets `agent_driver.py` inject unsave.json content over CDP for the Terminal B gate. When syncing the userscript from `main`, re-apply the bridge block (and its `runUnsaveFromPayloadText` / `loadAiResultsFromPayloadText` helpers in `AiReviewUtils`) and keep the full-branch version number ahead of lite's.
