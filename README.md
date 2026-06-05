# ThreadSieve

[繁體中文](README.zh-TW.md)

ThreadSieve is a local automation pipeline that turns Threads saved posts into categorized markdown notes, with optional AI-post cleanup and image OCR.

Two coupled layers: `userscripts/threads-scriber-auto.user.js` (browser, Tampermonkey) and `scripts/*.py` (Python pipeline).

---

## What it does

```
[Browser scrape via ThreadSieve userscript] ─→ catch.json (fixed path)
                                              │
                                              ▼ (mtime + debounce)
                          scripts/watch_pipeline.py
                                              │
                          ▼
          scripts/import_bookmarks_to_markdown.py
          (classify once → markdown notes + unsave.json)
                          │
                          ▼
                    scripts/image_ocr_to_markdown.py
                    (image OCR → ## 圖片文字)
                          │
                          ▼ (FS Access API poll lastModified)
   ThreadSieve userscript: auto-load + confirmed auto-unsave
```

Two usage paths after setup: **No Terminal** (scrape via browser panel + one classify command) or **With Terminal** (watcher auto-triggers on `catch.json` + agent-driven scrape with a confirmation gate).

---

## Prerequisites

| Requirement | Why needed |
| --- | --- |
| Python 3.11+ | watcher, classifier, note generator |
| Node.js 18+ | `chrome-ws` CLI (agent driver) |
| Google Chrome / Edge | browser automation via Chrome DevTools Protocol |
| Tampermonkey extension | userscript injection |
| Claude Code with [`superpowers-chrome`](https://github.com/obra/superpowers-chrome) plugin | provides the `chrome-ws` CDP CLI used by `agent_driver.py` |

---

## Install

### 0. Clone the repo

```powershell
git clone https://github.com/hikaru-yeh/thread-sieve.git
cd thread-sieve
```

### 1. superpowers-chrome (CDP automation, required for `agent_driver.py`)

`agent_driver.py` drives the browser through the [`superpowers-chrome`](https://github.com/obra/superpowers-chrome) plugin, which ships a `chrome-ws` Node.js CLI for Chrome DevTools Protocol commands.

#### A. Install the plugin

In Claude Code, install `superpowers-chrome` from the `obra/superpowers-marketplace` marketplace:

```text
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers-chrome@superpowers-marketplace
```

After installation the CLI lands at a path like the one below; use the version directory that exists on your machine:

```
C:\Users\<you>\.claude\plugins\cache\superpowers-marketplace\superpowers-chrome\2.1.0\skills\browsing\chrome-ws
```

Verify Node can run it:

```powershell
node "C:\Users\<you>\.claude\plugins\cache\superpowers-marketplace\superpowers-chrome\2.1.0\skills\browsing\chrome-ws" --help
```

#### B. Set `paths.chrome-ws-cli` in `config.json`

`agent_driver.py` and `push_userscript.py` require the `chrome-ws` CLI path. Set it in `config.json`:

```json
"paths": {
  "chrome-ws-cli": "C:/Users/<you>/.claude/plugins/cache/superpowers-marketplace/superpowers-chrome/2.1.0/skills/browsing/chrome-ws"
}
```

`CHROME_WS_PATH` is still accepted as a compatibility override, but new setups should use `config.json`.

#### C. Enable Chrome remote debugging

Chrome must be launched with `--remote-debugging-port=9222` **before** running any `agent_driver.py` commands.

`superpowers-chrome` can also launch Chrome with `chrome-ws start`, but its default behavior may choose a dynamic port. ThreadSieve's scripts and local hooks expect port `9222`, so use the fixed-port launcher below. If you choose to launch via `chrome-ws start`, pin the port with `--port=9222` or `CHROME_WS_PORT=9222`.

Chrome 136+ requires remote debugging to use a non-default user data directory. That directory is a separate Chrome profile, so extensions and login cookies live there. Use the same `--user-data-dir` every time; otherwise Chrome starts with a fresh profile and you will need to install Tampermonkey and log in again.

**Option 1 — PowerShell launcher**

Close all existing Chrome windows first. If Chrome is already running without the flag, Windows may reuse that process and the debugging port will not open.

```powershell
$profileDir = Join-Path $env:LOCALAPPDATA "ThreadSieve\ChromeDebugProfile"
New-Item -ItemType Directory -Force $profileDir | Out-Null
Start-Process "chrome.exe" -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=`"$profileDir`"",
  "https://www.threads.com/saved"
)
```

If `chrome.exe` is not found, use the full Chrome path:

```powershell
Start-Process "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=`"$profileDir`"",
  "https://www.threads.com/saved"
)
```

**Option 2 — shortcut (recommended for daily use)**

1. Copy the Chrome shortcut on your desktop / taskbar.
2. Right-click → Properties → Target, append ` --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ThreadSieve\ChromeDebugProfile" https://www.threads.com/saved`.
3. Always open Chrome through this shortcut, then install Tampermonkey and log in to Threads once inside this debug profile.

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ThreadSieve\ChromeDebugProfile" https://www.threads.com/saved
```

Verify the port is open:

```powershell
Invoke-WebRequest http://localhost:9222/json | Select-Object -Expand Content
```

Should return a JSON list of open tabs.

#### D. Agent hooks guard this preflight

This repo contains local hooks for both agent environments:

- `.claude/settings.json` runs `.claude/hooks/check-chrome-debug.ps1` before Claude Code shell commands.
- `.codex/hooks.json` runs `.codex/check-chrome-debug.ps1` through `.codex/check-chrome-debug.cmd` before Codex shell commands.

Both hooks only target `agent_driver.py` and `push_userscript.py`. They block those commands when `127.0.0.1:9222` is not reachable, so agents do not fall back to Edge, a fresh non-debug Chrome window, or manual Tampermonkey edits.

---

### 2. Python side

```powershell
cd path\to\threads-sieve
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
copy config.json.example config.json
```

Edit `.env`: fill in `GEMINI_API_KEY`.

Edit `config.json`:

| Key | What to set |
| --- | --- |
| `paths.catch-json` | Path to `data/catch.json` (relative or absolute) |
| `paths.unsave-json` | Path to `data/unsave.json` (relative or absolute) |
| `paths.markdown-output-root` | Where markdown notes are written (default: `output`) |
| `paths.chrome-ws-cli` | Full path to the `chrome-ws` CLI from step 0 |
| `categories` | Ordered list of categories the classifier can output |
| `unsaved-categories` | Subset of `categories` whose posts get added to `unsave.json` |
| `hints` | Free-text rules injected into the Gemini prompt to guide edge-case decisions |

`category-overrides` is optional — keyword/regex rules that force a category before calling Gemini.

ThreadSieve includes its own markdown note generator at `scripts/import_bookmarks_to_markdown.py`; it no longer calls a sibling `PROJECT_threads-to-note` repo. Markdown notes are written to `config.json` → `paths.markdown-output-root` (default: `output`).

### 3. Browser side (one-time setup)

1. Launch Chrome with `--remote-debugging-port=9222` (see above).
2. Navigate to `https://www.threads.com/saved` and keep this tab open.
3. Install [Tampermonkey](https://www.tampermonkey.net/) in Chrome / Edge.
4. If you previously installed `threads-scriber.user.js` in this Chrome profile, disable it first. First-time ThreadSieve installs can skip this step.
5. Open `userscripts/threads-scriber-auto.user.js` and click "Install" in Tampermonkey.
6. Reload the `/saved` tab. A floating panel "ThreadSieve · Auto AI Sync" appears bottom-right.

The `catch.json` autosave grant, `unsave.json` binding, and `agent_driver.py probe` check are part of the daily SOP below. Treat browser File System Access handles as per-run setup because Chrome may require the grants again before writing or reading files.

---

## Daily usage SOP

Two usage paths. Choose based on your setup:

| | Path 1 — No Terminal | Path 2 — Terminal watcher + agent scrape |
| --- | --- | --- |
| Requires `agent_driver.py` | No | Yes |
| Requires Chrome debug port | No | Yes |
| Classify trigger | Manual (one command) | Automatic (watcher detects `catch.json`) |
| Best for | Occasional use, quick runs | Daily automation |

---

### Path 1 — No Terminal

Scrape via the browser panel, then run classify once by hand.

#### Step 1 · Prepare the browser session

1. Open Chrome and navigate to `https://www.threads.com/saved`.
2. If needed, reload the `/saved` tab so the **ThreadSieve** panel and **Auto AI Sync** panel appear.
3. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.
4. In the **Auto AI Sync panel**: click **綁定 unsave.json** → pick `data/unsave.json`.
5. Tick **自動載入 unsave.json**.

#### Step 2 · Scrape via the panel

1. Enter a cutoff date in the ThreadSieve panel date input.
2. Click **清空結果** to clear any leftover results from a previous run.
3. Click **開始抓取** and wait for `狀態` to show `完成` or `待機中`.

#### Step 3 · Run classify

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/import_bookmarks_to_markdown.py
```

This classifies every post once and writes both markdown notes and `unsave.json`. Image OCR runs automatically for posts whose category matches `config.json` → `image-ocr.trigger-categories`.

#### Step 4 · Confirm unsave in the browser

The Auto AI Sync panel polls `unsave.json` every 3 s. Once it loads the new file it shows the candidate count and `generatedAt` timestamp.

- Click **立即檢查** to force an immediate poll.
- Tick **載入後自動取消儲存** before the file updates, or click the unsave button manually, to unsave the AI candidates.

---

### Path 2 — Terminal watcher + agent scrape (automated)

Runs the full pipeline automatically. Requires Chrome with `--remote-debugging-port=9222` and `config.json` → `paths.chrome-ws-cli` set.

#### Terminal A — start the watcher (keep running)

```powershell
cd path\to\threads-sieve
.\start_pipeline.ps1
```

Logs stream to console and `pipeline.log`. Stop with `Ctrl+C`.

#### Terminal B — agent-driven scrape

##### Step 1 · Prepare the browser session

1. Launch Chrome with `--remote-debugging-port=9222` using the same debug profile from setup.
2. Open `https://www.threads.com/saved` and keep this tab open.
3. If needed, reload the `/saved` tab so the **ThreadSieve** panel and **Auto AI Sync** panel appear.
4. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.
5. In the **Auto AI Sync panel**: click **綁定 unsave.json** → pick `data/unsave.json`.
6. Tick **自動載入 unsave.json**.
7. Leave **載入後自動取消儲存** off when using the Terminal B confirmation gate; `agent_driver.py scrape` will run the confirmed one-shot unsave after you type `y`.
8. Optional: click **立即檢查** to force one AI classification load. If it succeeds, the small Auto AI Sync panel closes so it no longer covers the main panel.

##### Step 2 · Verify panel readiness

```powershell
python scripts/agent_driver.py probe
```

Expected output ends with `OK: panel ready for agent-driven scrape`.

**If it reports problems:**

| Problem | Fix |
| --- | --- |
| `panel missing` | Reload the `/saved` tab; wait for Tampermonkey to inject |
| `scriptVersion=X expected 0.3.2` | Re-install `userscripts/threads-scriber-auto.user.js` in Tampermonkey |
| `autosave (catch.json) not bound` | Click **設定自動存檔** in the panel, pick `data/catch.json`; re-run probe |
| `unsave.json handle not bound in AutoAiSync panel` | Click **綁定 unsave.json** in the Auto AI Sync panel, pick `data/unsave.json`; re-run probe |
| `AutoAiSync panel missing` | Reload `/saved` tab; this refers to the Auto AI Sync panel |

##### Step 3 · Trigger scrape

```powershell
# Capture everything since 2010 (all saves):
python scripts/agent_driver.py scrape --cutoff 2010-01-01 --wait-seconds 300

# Or limit to a recent window (faster, fewer Gemini tokens):
python scripts/agent_driver.py scrape --cutoff 2025-01-01 --wait-seconds 120
```

`--cutoff` sets the date input in the panel before clicking 開始抓取.  
Each `scrape` run first clicks **清空結果** so `catch.json` contains only the current run, not stale panel/localStorage items from an earlier cutoff.
`--wait-seconds` polls `狀態` until idle (`待機中` / `完成` / `已停止`) or timeout.

`--no-unsave-confirm` skips the Terminal B confirmation gate and lets browser auto-unsave run as soon as `unsave.json` updates. `--unsave-timeout-seconds` (default `600`) bounds how long the gate waits for the watcher to write a fresh `unsave.json` after scrape completes.

##### Step 4 · Wait for pipeline

Watch Terminal A. After `catch.json` stabilises, the watcher runs the note workflow, which classifies each post once and writes both markdown notes and `unsave.json`:

```
pipeline starting: items=N
[notes]    exit code: 0
```

`unsave.json` and markdown notes are both ready at this point.

After `notes` finishes, `scripts/image_ocr_to_markdown.py` reads this run's `catch.json` and `unsave.json`. For posts whose classification reason matches `config.json` → `image-ocr.trigger-categories`, it renders the Threads post with Playwright, OCRs attached images, and appends a `## 圖片文字` section to the matching markdown note. Gemini OCR is the default backend; Chandra can be selected in `config.json`.

##### Step 5 · Terminal B confirmation gate

After a fresh `unsave.json` is generated, Terminal B prints each candidate as `作者:<author>| 貼文:<first sentence>` and asks `確認執行?(y/n)`.

- Type `y` to force-load `unsave.json` and run the one-shot unsave flow.
- Type `n` to keep `unsave.json` on disk and leave browser auto-unsave disabled; nothing on Threads changes.

The gate sets browser auto-unsave to off at the start of every `scrape` run unless `--no-unsave-confirm` is passed. The ThreadSieve userscript still polls `unsave.json` every 3 s and shows the loaded `generatedAt` timestamp and candidate count in the Auto AI Sync panel.

Manual export, manual AI classification loading, manual selection, and debug tools are still available in the ThreadSieve panel, but they are collapsed under **手動工具** and **診斷** to keep the normal workflow uncluttered.

---

### Quick-check commands

```powershell
# Dump raw panel state:
python scripts/agent_driver.py status

# Click an arbitrary panel button (e.g. stop):
python scripts/agent_driver.py click stop
```

---

## Backfill existing markdown image OCR

Use `scripts/backfill_image_ocr.py` when older markdown notes were already written before image OCR existed. The tool scans a markdown file or folder, finds likely OCR-missing stubs, fetches the Threads post images, OCRs them with the configured image OCR backend, and inserts `## 圖片文字` before `## Sources`.

Default candidate rules:

- frontmatter has `status: stub`
- frontmatter has `網址` or `url`
- the note does not already contain `## 圖片文字`
- the non-frontmatter body is shorter than `--min-content-chars` (default: `800`)

Preview a folder without fetching images, calling the OCR backend, or editing files:

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --dry-run
```

For date-based patch work, ask the agent to filter files first, then run the script per matched file. `backfill_image_ocr.py` intentionally does not include a modified-date filter because date patching is an occasional repair workflow, not the normal batch mode.

Example agent prompt:

```text
Use `scripts/backfill_image_ocr.py`.

Recursively scan:
<wiki-folder>

Only select `.md` files whose filesystem LastWriteTime date is YYYY-MM-DD,
then run `scripts/backfill_image_ocr.py --path "<file>"` for each selected file.

Do not pass the entire wiki folder to the script for this date-scoped repair.
Use the script defaults: process only `status: stub`, short body, frontmatter `網址` or `url`,
and no existing `## 圖片文字`.

Write a JSONL log and report processed / skipped / failed / no_images.
```

Write an explicit JSONL log:

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --log data/backfill-image-ocr.jsonl
```

Each considered file gets one JSONL event with `processed`, `skipped`, `failed`, or `no_images`. Individual file failures are soft and do not stop the batch. Use `--force` only when you want to replace an existing `## 圖片文字` section.

---

## Configuration

### `config.json` — paths, classification logic, and OCR behavior

Edit this file to customise local paths and per-user categories without touching Python.

| Key | Default | Used by |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | watcher, note workflow, userscript handle |
| `paths.unsave-json` | `data/unsave.json` | note workflow, OCR, watcher, userscript handle |
| `paths.markdown-output-root` | `output` | markdown note output root; ThreadSieve writes notes here and OCR scans this tree |
| `paths.chrome-ws-cli` | _required for browser automation_ | `agent_driver.py`, `push_userscript.py` |
| `categories` | project example list | Ordered list of categories the Gemini classifier can output |
| `unsaved-categories` | project example subset | Subset of `categories` that map to `decision="ai"` — posts in these categories get auto-unsaved |
| `category-overrides` | `[]` | Optional keyword / regex rules that force a category before calling Gemini; use this for personal taxonomy rules |
| `image-ocr` | see below | Non-secret image OCR behavior: backend, Chandra method, prompt type, max output tokens, headers/footers toggle, and trigger categories |
| `hints` | project example rules | Free-text rules injected into the Gemini prompt to guide priority decisions between categories |

Path values may be relative to the project root or absolute local paths. For Windows paths in JSON, forward slashes are easiest: `C:/Users/<you>/...`.

```json
"paths": {
  "catch-json": "data/catch.json",
  "unsave-json": "data/unsave.json",
  "markdown-output-root": "output",
  "chrome-ws-cli": "C:/Users/<you>/.claude/plugins/cache/superpowers-marketplace/superpowers-chrome/2.1.0/skills/browsing/chrome-ws"
}
```

Optional category override example:

```json
"category-overrides": [
  {
    "category": "Project",
    "keywords": ["project mercury"],
    "regex": ["#project\\b"]
  }
]
```

The normal watcher path classifies once inside `scripts/import_bookmarks_to_markdown.py`, then writes markdown notes and `unsave.json` from that same result. `scripts/classify_to_scribe_ai.py` is still available as a standalone compatibility/debug command; its CLI-only `--unsaved-categories` override applies only to that standalone run.

Default OCR config:

```json
"image-ocr": {
  "backend": "gemini",
  "method": "vllm",
  "prompt-type": "ocr_layout",
  "max-output-tokens": 12384,
  "include-headers-footers": false,
  "trigger-categories": ["AI", "Claude Code"]
}
```

Set `"backend": "chandra"` to use Chandra. With `"method": "vllm"`, Chandra calls the OpenAI-compatible endpoint configured by the `VLLM_*` keys in `.env`. CLI flags such as `--ocr-backend chandra` and environment variables such as `IMAGE_OCR_BACKEND=chandra` still work as one-off overrides.

`CATCH_PATH`, `UNSAVE_PATH`, `MARKDOWN_OUTPUT_PATH`, `THREADS_MARKDOWN_OUTPUT`, and `CHROME_WS_PATH` are still accepted as compatibility aliases, but new setups should use `config.json`.

### `.env` — secrets and runtime tuning

| Key | Default | Used by |
| --- | --- | --- |
| `GEMINI_API_KEY` | _required_ | classifier, and image OCR when `image-ocr.backend` is `gemini` |
| `CLASSIFIER_MODEL` | `gemini-2.5-flash` | classifier |
| `IMAGE_OCR_ENABLED` | `true` | OCR step toggle |
| `IMAGE_OCR_MODEL` | `gemini-2.5-flash` | Gemini image OCR model when `image-ocr.backend` is `gemini` |
| `MODEL_CHECKPOINT` | `datalab-to/chandra-ocr-2` | Chandra model setting when `image-ocr.backend` is `chandra` |
| `MAX_OUTPUT_TOKENS` | `12384` | Chandra max output tokens; can be overridden by `image-ocr.max-output-tokens` |
| `VLLM_API_BASE` | `http://localhost:8000/v1` | Chandra vLLM OpenAI-compatible endpoint |
| `VLLM_MODEL_NAME` | `chandra` | Chandra vLLM served model name |
| `VLLM_GPUS` | `0` | Chandra vLLM server GPU selection |
| `DEBOUNCE_SECONDS` | `2.0` | watcher |
| `POLL_SECONDS` | `1.0` | watcher |

The public Chandra defaults in `.env.example` come from [datalab-to/chandra](https://github.com/datalab-to/chandra); check that repo for the latest upstream settings.

---

## Tests

```powershell
cd path\to\threads-sieve
.\.venv\Scripts\Activate.ps1
pip install pytest
pytest tests/
```

Tests cover:
- `classify_to_scribe_ai.py` — standalone compatibility classifier output schema, error / unsure buckets, custom categories
- `import_bookmarks_to_markdown.py` — single-pass classification feeding both markdown notes and `unsave.json`
- `watch_pipeline.py` — debounce, missing-file handling, `.env` loader
- `image_ocr_to_markdown.py` — trigger filtering, markdown matching, OCR backend selection, OCR section insertion, DOM image filtering
- `backfill_image_ocr.py` — frontmatter URL extraction, candidate skipping, dry-run behavior, OCR section insertion/replacement, batch summary

---

## Known limitations

- **Browser must be open + on the saved page** for auto-unsave to fire. The watcher will still produce `unsave.json` and markdown notes regardless, but the unsave step is a no-op until you visit `/saved`.
- **File System Access grants are per-run setup** in the daily SOP. If the Auto AI Sync panel status shows "handle: not bound" or `probe` reports missing handles, re-select `data/catch.json` and `data/unsave.json`.
- **Gemini quota**: each scrape classifies each post once, then uses Gemini again for title generation. If `image-ocr.backend` is `gemini`, OCR also consumes quota from the same key.
- **Chandra OCR is optional**: set `config.json` → `image-ocr.backend` to `chandra`. For `method=vllm`, you must provide a reachable Chandra/vLLM OpenAI-compatible endpoint through `VLLM_API_BASE`.
- **Chandra CLI still needs a viable backend**: `chandra --method vllm` is a CLI client and still requires a running vLLM server. `chandra --method hf` runs locally, but Chandra OCR 2 downloads a 10GB+ model and can be impractically slow or fail on low-resource Windows machines. Use Gemini OCR when no suitable Chandra backend is available.
- **Markdown image OCR scans the markdown root**: set `config.json` → `paths.markdown-output-root` if you do not want the default `output` folder.
- **Markdown image OCR uses Playwright**: the OCR step renders each matching Threads post to find carousel images. If Playwright browser binaries are missing, run `playwright install chromium`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Watcher prints "missing required config" | `config.json` paths are empty | Verify `paths.catch-json` and `paths.unsave-json` in `config.json` |
| `catch.json` written but watcher idle | mtime change happened during the debounce window of another run | Wait `DEBOUNCE_SECONDS`; or shrink `POLL_SECONDS` |
| `notes` subprocess fails with `GEMINI_API_KEY missing` | env not propagated to subprocess | Confirm key is in `.env` (not just shell), restart watcher |
| OCR fails with `GEMINI_API_KEY missing` | `image-ocr.backend` is `gemini` but no key is available | Set `GEMINI_API_KEY`, or switch `config.json` → `image-ocr.backend` to `chandra` |
| Chandra OCR cannot connect to vLLM | `image-ocr.backend=chandra` but `VLLM_API_BASE` is not reachable | Start your Chandra/vLLM server or update `VLLM_API_BASE` |
| Userscript panel never shows an AI classification load | handle not bound, permission revoked, or `autoLoad` off | Click **綁定 unsave.json** again, tick **自動載入 unsave.json**, or click **立即檢查**; check browser console for `[threads-sieve]` warnings |
| Auto-unsave skipped with "not on saved page" | Tab navigated away | Switch the tab back to `/saved` |
| `probe` reports autosave not bound | Current browser session has not granted the `catch.json` autosave handle | Click **設定自動存檔** in the panel and pick `data/catch.json`, then re-run probe |
| `scrape` exits 2 with timeout | Scrape still running (large backlog) or panel stalled | Increase `--wait-seconds`; check panel status with `python scripts/agent_driver.py status` |
| `catch.json` stays 0 bytes after scrape | Autosave handle not bound | Re-grant via 設定自動存檔, then re-run scrape |
