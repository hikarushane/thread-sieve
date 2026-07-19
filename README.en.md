# ThreadSieve (full / power-user)

[繁體中文](README.md)

> **Latest update (2026-07-18)**: browser panel redesign — the manual-tools section and the Auto AI Sync panel are gone, replaced by a single big **取消儲存** (unsave) button that re-picks `unsave.json` on every run, eliminating accidental runs against stale classification results; install is now a one-line command; new macOS double-click launcher. Full history in [RELEASE_NOTES.md](RELEASE_NOTES.md).

> **This branch is the power-user build** — includes `watch_pipeline.py`, `agent_driver.py`, and Chandra/vLLM OCR backend. Requires Node.js, Claude Code + `superpowers-chrome` plugin, and Chrome `--remote-debugging-port=9222`.  
> If you just want to **double-click and go** (no plugin, no terminal), use the [`lite` branch](https://github.com/hikarushane/thread-sieve) — it's the repo's default branch.

The problem with Threads bookmarks:

  ❌ saved hundreds of posts
  ❌ zero categories
  ❌ can't find anything
  ❌ they just sit there rotting

ThreadSieve is a local automation pipeline that turns Threads saved posts into categorized markdown notes, and unsaves posts in specified categories with a one-button flow.

Post content passed into classification and note generation includes the main post text, comments from the post author in the same thread, and text extracted from post images with OCR. When the saved item is a reply, the note also carries the reply's single-line ancestor context (the full chain from the root post down to the reply) and a reply section (the original poster's replies plus substantive comments, rendered collapsed).

Two coupled layers:

- `userscripts/threads-scriber-auto.user.js` — Tampermonkey userscript; scrapes the Threads saved page and writes `catch.json`.
- `scripts/*.py` — Python pipeline; LLM classification, markdown notes, image OCR, and agent-driven browser operations.

---

## What it does

![ThreadSieve flow overview](docs/flow-overview.png)

Two usage paths after setup: **No-typing (double-click)** (scrape via browser panel + double-click `run_classify.cmd` / `.command`) or **With Terminal** (watcher auto-triggers on `catch.json` + agent-driven scrape).

---

## Prerequisites

| Requirement | Why needed |
| --- | --- |
| Python 3.10+ (not needed for the one-line install — uv downloads 3.12 automatically) | classifier, markdown generator, image OCR |
| Google Chrome / Edge | browser |
| Tampermonkey extension | userscript injection |
| LLM API key (one of Gemini / Anthropic / OpenAI; Gemini by default) | classification + titles + image OCR |
| Node.js 18+ (Path 2 only) | `chrome-ws` CLI (agent driver) |
| Claude Code with [`superpowers-chrome`](https://github.com/obra/superpowers-chrome) plugin (Path 2 only) | provides the `chrome-ws` CDP CLI used by `agent_driver.py` |

---

## Install

### 0. One-line install (clone + Python environment)

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/hikarushane/thread-sieve/main/install.ps1 | iex
```

**macOS (Terminal):**

```bash
curl -fsSL https://raw.githubusercontent.com/hikarushane/thread-sieve/main/install.sh | bash
```

One line does it all: clone the repo → install [uv](https://docs.astral.sh/uv/) if missing → create a Python 3.12 virtual environment → install dependencies and Chromium → generate `.env` / `config.json`. **It doesn't matter which Python version your system has**: uv downloads the right one automatically and uses it only inside this project's `.venv`, leaving your existing setup untouched.

> Note: the one-line install clones the default branch (`main`, i.e. lite). To use this full branch, run `git checkout full` inside the project directory after the install finishes.

<details>
<summary>Prefer not to <code>curl | bash</code>? Manual steps here</summary>

```powershell
# Windows (PowerShell); requires Python 3.10+
git clone https://github.com/hikarushane/thread-sieve.git
cd thread-sieve
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
copy config.json.example config.json
```

```bash
# macOS (Terminal); requires Python 3.10+
git clone https://github.com/hikarushane/thread-sieve.git
cd thread-sieve
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
cp config.json.example config.json
```

</details>

### 1. Fill in the config

Edit `.env`: fill in the API key for your chosen provider (default Gemini → `GEMINI_API_KEY`; see "LLM provider" below to switch).

Edit `config.json`:

| Key | What to set |
| --- | --- |
| `paths.catch-json` | Path to `data/catch.json` (relative or absolute) |
| `paths.unsave-json` | Path to `data/unsave.json` (relative or absolute) |
| `paths.markdown-output-root` | Where markdown notes are written (default: `output`) |
| `paths.chrome-ws-cli` | Full path to the `chrome-ws` CLI from step 0 |
| `categories` | Ordered list of categories the classifier can output |
| `unsaved-categories` | Subset of `categories` whose posts get added to `unsave.json` |
| `hints` | Free-text rules injected into the classifier prompt for edge cases |
| `llm.provider` (optional) | `gemini` (default) / `anthropic` / `openai` |

`category-overrides` is optional — keyword/regex rules that force a category before calling the LLM.

ThreadSieve includes its own markdown note generator at `scripts/import_bookmarks_to_markdown.py`; it no longer calls a sibling `PROJECT_threads-to-note` repo. Markdown notes are written to `config.json` → `paths.markdown-output-root` (default: `output`).

### 2. superpowers-chrome (CDP automation, required for `agent_driver.py`; Path 2 only)

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

### 3. Browser side (one-time setup)

1. Launch Chrome with the debug profile set up above (plain Chrome / Edge is fine if you only use Path 1). Navigate to `https://www.threads.com/saved` and keep this tab open.
2. Install [Tampermonkey](https://www.tampermonkey.net/) in this Chrome profile.
3. If you previously installed `threads-scriber.user.js` in this Chrome profile, disable it first. First-time ThreadSieve installs can skip this step.
4. Open `userscripts/threads-scriber-auto.user.js` and click "Install" in Tampermonkey.
5. Reload the `/saved` tab. The **ThreadSieve** panel appears (the Auto AI Sync panel is gone as of userscript 0.4.1).

The `catch.json` autosave grant and the `agent_driver.py probe` check are part of the daily SOP below. Treat browser File System Access handles as per-run setup because Chrome may require the grants again. `unsave.json` is never persistently bound — every unsave run re-picks the file (by design).

---

## Daily usage SOP

Two usage paths. Choose based on your setup:

| | Path 1 — No-typing (double-click) | Path 2 — Terminal watcher + agent scrape |
| --- | --- | --- |
| Requires `agent_driver.py` | No | Yes |
| Requires Chrome debug port | No | Yes |
| Classify trigger | Double-click `run_classify.cmd` / `.command` | Automatic (watcher detects `catch.json`) |
| Best for | Occasional use, quick runs | Daily automation |

---

### Path 1 — No-typing (double-click)

Scrape via the browser panel, then double-click `run_classify.cmd` / `.command` to run classify once. No commands to type.

#### Step 1 · Prepare the browser session

1. Open Chrome and navigate to `https://www.threads.com/saved`.
2. If needed, reload the `/saved` tab so the **ThreadSieve** panel appears.
3. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.

#### Step 2 · Scrape via the panel

1. Enter a cutoff date in the ThreadSieve panel date input.
2. Click **清空結果** to clear any leftover results from a previous run.
3. Click **開始抓取** and wait for `狀態` to show `完成` or `待機中`.

#### Step 3 · Run classify

- **Windows**: double-click `run_classify.cmd` in the project root.
- **macOS**: double-click `run_classify.command` in the project root (first run may need `chmod +x run_classify.command`, or right-click → Open to get past Gatekeeper).

A console/Terminal window opens, activates `.venv`, and runs `scripts/import_bookmarks_to_markdown.py`. While it runs it prints per-bookmark progress lines `[n/total] title category` (already-imported posts are marked as skipped), then a summary line (total bookmarks, progress, markdown output path), and finally `[DONE]` or `[FAILED]`, waiting for any key.

Optional desktop shortcut:

- **Windows**: right-click `run_classify.cmd` → Send to → Desktop (create shortcut).
- **macOS**: ⌥⌘-drag `run_classify.command` to the Desktop to make an alias.

Then double-click the shortcut from anywhere.

This classifies every post once and writes both markdown notes and `unsave.json`. Image OCR runs automatically for posts whose category matches `config.json` → `image-ocr.trigger-categories`.

Fallback for users who prefer a shell:

```powershell
# Windows
.\.venv\Scripts\Activate.ps1
python scripts/import_bookmarks_to_markdown.py
```

```bash
# macOS
source .venv/bin/activate
python scripts/import_bookmarks_to_markdown.py
```

#### Step 4 · Confirm unsave in the browser

In the ThreadSieve panel, click the big **取消儲存** button → pick `data/unsave.json` in the file picker → the panel shows the candidate count and highlights the posts → a confirm dialog runs the unsave pass after you accept.

Re-picking the file on every run is deliberate: the file pick itself is your confirmation that the latest classification result is being used, preventing accidental runs against a stale file.

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
3. If needed, reload the `/saved` tab so the **ThreadSieve** panel appears.
4. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.

> **Userscript 0.4.2 (full-branch build)**: 0.4.1 removed the Auto AI Sync panel and auto-unsave; the full-branch userscript adds an agent bridge (`window.ThreadSieveAgent`) on top, so the Terminal B gate injects the `unsave.json` content straight into the page and runs the one-shot flow. The terminal `y/n` replaces the file-pick confirmation — the file is re-read from disk at execution time, so the anti-stale-file guarantee still holds. For Path 2, install the **full-branch** `userscripts/threads-scriber-auto.user.js` (0.4.2).

##### Step 2 · Verify panel readiness

```powershell
python scripts/agent_driver.py probe
```

Expected output ends with `OK: panel ready for agent-driven scrape`.

**If it reports problems:**

| Problem | Fix |
| --- | --- |
| `panel missing` | Reload the `/saved` tab; wait for Tampermonkey to inject |
| `scriptVersion=X expected 0.4.2` | Installed userscript is not the full-branch build (e.g. still lite 0.4.1, which has no agent bridge) | Re-install the full-branch `userscripts/threads-scriber-auto.user.js` |
| `autosave (catch.json) not bound` | Click **設定自動存檔** in the panel, pick `data/catch.json`; re-run probe |

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

##### Step 4 · Wait for pipeline

Watch Terminal A. After `catch.json` stabilises, the watcher runs the note workflow, which classifies each post once and writes both markdown notes and `unsave.json`:

```
pipeline starting: items=N
[notes]    exit code: 0
```

`unsave.json` and markdown notes are both ready at this point.

After `notes` finishes, `scripts/image_ocr_to_markdown.py` reads this run's `catch.json` and `unsave.json`. For posts whose classification reason matches `config.json` → `image-ocr.trigger-categories`, it renders the Threads post with Playwright, OCRs attached images, and appends a `## 圖片文字` section to the matching markdown note. Gemini OCR is the default backend; Chandra can be selected in `config.json`.

##### Step 5 · Terminal B confirmation gate

After the watcher writes a fresh `unsave.json`, Terminal B prints each candidate as `作者:<author>| 貼文:<first sentence>` and asks `確認執行?(y/n)`:

- Type `y`: the gate re-reads `unsave.json` from disk, injects it through the agent bridge, runs the one-shot unsave, and reports `verified/attempted/failed/remaining`.
- Type `n`: `unsave.json` stays on disk and the browser is left untouched.

Pass `--no-unsave-confirm` to skip the gate (scrape only) and run the unsave manually from the browser panel instead. `--unsave-timeout-seconds` (default `600`) bounds how long the gate waits for a fresh `unsave.json`.

As of 0.4.1 the ThreadSieve panel keeps only the scrape controls and the single **取消儲存** button; the old manual tools, manual AI classification loading, and debug panels have been removed.

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

## LLM provider

ThreadSieve uses an LLM for classification, title generation, and image OCR. The default backend is Google Gemini (SDK), but `config.json` or `.env` can switch to Anthropic Claude or OpenAI ChatGPT.

| Provider  | API key env var       | Default text model     | Default vision model   |
|-----------|-----------------------|------------------------|------------------------|
| Gemini    | `GEMINI_API_KEY`      | `gemini-2.5-flash`     | `gemini-2.5-flash`     |
| Anthropic | `ANTHROPIC_API_KEY`   | `claude-sonnet-4-6`    | `claude-sonnet-4-6`    |
| OpenAI    | `OPENAI_API_KEY`      | `gpt-4o-mini`          | `gpt-4o`               |

Pick a provider with `LLM_PROVIDER=...` in `.env`, or set `"llm": { "provider": "..." }` in `config.json`. Only the API key for the selected provider needs to be filled in.

Supporting only provider APIs — and not local agent CLIs such as `claude -p` / `codex exec` — is a deliberate design decision: for batch classification, per-call CLI startup overhead, subscription-quota consumption, and the inability to set `temperature=0` make CLIs a poor fit. See [docs/decisions/ADR-001](docs/decisions/ADR-001-use-llm-provider-apis-not-agent-clis.md) for the full rationale.

Per-stage model overrides: env vars `THREADS_LLM_CLASSIFIER_MODEL` / `THREADS_LLM_TITLE_MODEL` / `THREADS_LLM_OCR_MODEL`, or `config.json` keys `llm.text-model` / `llm.title-model` / `llm.vision-model`.

Note: the standalone `scripts/image_ocr_to_markdown.py` CLI currently supports only `--ocr-backend gemini`; the multi-provider factory is wired into the main pipeline (`scripts/import_bookmarks_to_markdown.py` + workflow).

---

## Ancestor context and replies for saved replies

When the saved bookmark is a reply (not a root post), the classify stage opens the post permalink anonymously and extracts from the page's embedded data:

- **Ancestor context**: the full single line from the root post down to the saved reply, written into the note's `## 上文脈絡` section (nested blockquotes, each post labeled with `@author`).
- **Reply section**: the original poster's replies (paired with the comment they answer) plus comments above a length threshold, written into a collapsible Obsidian callout (`> [!quote]- 回覆（N 則…）`), collapsed by default.
- Frontmatter gains `saved_kind: root|reply`, marking whether the saved item is a root post or a reply.

The ancestor context (but never the reply section) is also fed to classification and title generation, improving accuracy for saved replies — with no extra network requests or LLM quota.

---

## Configuration

### `config.json` — paths, classification logic, and OCR behavior

Edit this file to customise local paths and per-user categories without touching Python.

| Key | Default | Used by |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | userscript writes, classify/watcher reads |
| `paths.unsave-json` | `data/unsave.json` | classify writes, userscript reads |
| `paths.markdown-output-root` | `output` | markdown note root; OCR scans this tree |
| `paths.chrome-ws-cli` | _required for browser automation_ | `agent_driver.py`, `push_userscript.py` (Path 2 only) |
| `categories` | example list | classifier output categories |
| `unsaved-categories` | example subset | posts in these categories are written to `unsave.json` |
| `category-overrides` | `[]` | optional keyword/regex forced categories |
| `hints` | example rules | classifier prompt nudges |
| `llm.provider` | `gemini` | LLM provider: `gemini` / `anthropic` / `openai` |
| `llm.text-model` / `title-model` / `vision-model` | provider default | per-stage model overrides (leave unset for provider defaults) |
| `image-ocr.backend` | `gemini` | `gemini` or `chandra` (Chandra config below) |
| `image-ocr.trigger-categories` | `["AI"]` | categories that trigger image OCR |
| `thread-context.enabled` | `true` | ancestor/replies capture toggle; `false` restores the previous behavior |
| `thread-context.min-reply-chars` | `12` | minimum comment length for the reply section (the original poster's replies are exempt) |
| `thread-context.max-replies` | `30` | maximum reply *threads* kept (one thread may contain several messages; the original poster's replies are always kept and don't count toward the cap; extras are truncated, noted in the callout header) |

Path values may be relative to the project root or absolute local paths. For Windows absolute paths in JSON you MUST use forward slashes (`C:/Users/<you>/...`) or escape every backslash as `\\` (`C:\\Users\\<you>\\...`). A single `\` is the JSON escape character, so `"D:\shane\..."` raises `json.decoder.JSONDecodeError: Invalid \escape`.

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
| `LLM_PROVIDER` | `gemini` | `gemini` / `anthropic` / `openai` (also settable via `llm.provider` in `config.json`) |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | fill in only the one for the selected provider |
| `THREADS_LLM_CLASSIFIER_MODEL` / `THREADS_LLM_TITLE_MODEL` / `THREADS_LLM_OCR_MODEL` | provider default | per-stage model overrides |
| `CLASSIFIER_MODEL` / `IMAGE_OCR_MODEL` | — | legacy Gemini overrides, still honored; prefer `THREADS_LLM_*` |
| `IMAGE_OCR_ENABLED` | `true` | OCR step toggle |
| `THREADS_CONTEXT_ENABLED` | `true` | overrides `thread-context.enabled` |
| `THREADS_CONTEXT_MIN_REPLY_CHARS` | `12` | overrides `thread-context.min-reply-chars` |
| `THREADS_CONTEXT_MAX_REPLIES` | `30` | overrides `thread-context.max-replies` |
| `MODEL_CHECKPOINT` | `datalab-to/chandra-ocr-2` | Chandra model setting when `image-ocr.backend` is `chandra` |
| `MAX_OUTPUT_TOKENS` | `12384` | Chandra max output tokens; can be overridden by `image-ocr.max-output-tokens` |
| `VLLM_API_BASE` | `http://localhost:8000/v1` | Chandra vLLM OpenAI-compatible endpoint |
| `VLLM_MODEL_NAME` | `chandra` | Chandra vLLM served model name |
| `VLLM_GPUS` | `0` | Chandra vLLM server GPU selection |
| `DEBOUNCE_SECONDS` | `2.0` | watcher |
| `POLL_SECONDS` | `1.0` | watcher |

The public Chandra defaults in `.env.example` come from [datalab-to/chandra](https://github.com/datalab-to/chandra); check that repo for the latest upstream settings.

The pipeline writes a `threads_events.jsonl` event log into the output directory; ancestor/replies capture outcomes are logged as `reply_fetch_fetched_structured` (structured parse succeeded) and `reply_fetch_fetched_fallback` (fell back to plain-text parsing) events.

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

- **Browser must be on `/saved`** to run the unsave pass (the button reports an error otherwise). The classify step still writes `unsave.json` and markdown regardless.
- **File System Access grants are per-run setup**. Re-pick `catch.json` for autosave if the panel loses the grant; `unsave.json` is re-picked on every unsave run by design.
- **LLM quota**: each classify run classifies every post once, then calls the LLM again for title generation and (when triggered) image OCR — all from the same API key.
- **Markdown image OCR scans the markdown root**: set `config.json` → `paths.markdown-output-root` if you do not want the default `output` folder.
- **Playwright is required for image OCR**: the OCR step renders each matching Threads post to find carousel images. If browser binaries are missing, run `playwright install chromium`.
- **The reply section only captures anonymously visible replies**: deeply nested replies and content behind the login wall are not collected.
- **Threads redesigns may break the embedded-data parse**: the pipeline then falls back to the previous plain-text parsing (that note temporarily has no ancestor/reply sections; the main content is unaffected), and `saved_kind` is a best-effort `root`.
- **Chandra OCR is optional**: set `config.json` → `image-ocr.backend` to `chandra`. For `method=vllm`, you must provide a reachable Chandra/vLLM OpenAI-compatible endpoint through `VLLM_API_BASE`.
- **Chandra CLI still needs a viable backend**: `chandra --method vllm` is a CLI client and still requires a running vLLM server. `chandra --method hf` runs locally, but Chandra OCR 2 downloads a 10GB+ model and can be impractically slow or fail on low-resource Windows machines. Use Gemini OCR when no suitable Chandra backend is available.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Double-clicking `run_classify.cmd`/`run_classify.command` shows `.venv not found` | venv never created | Run the one-line install once (pick the command for your OS) |
| Watcher prints "missing required config" | `config.json` paths are empty | Verify `paths.catch-json` and `paths.unsave-json` in `config.json` |
| classify exits with `json.decoder.JSONDecodeError: Invalid \escape` | Windows path in `config.json` uses single `\` | Use `/` (`D:/foo/bar`) or `\\` (`D:\\foo\\bar`) |
| classify / `notes` subprocess exits with `<PROVIDER>_API_KEY missing` | the selected provider's key not in `.env`, or the subprocess didn't pick it up | Confirm the matching `..._API_KEY=...` in `.env`; double-click again or restart the watcher |
| `catch.json` written but watcher idle | mtime change happened during the debounce window of another run | Wait `DEBOUNCE_SECONDS`; or shrink `POLL_SECONDS` |
| OCR fails with `GEMINI_API_KEY missing` | `image-ocr.backend` is `gemini` but no key is available | Set `GEMINI_API_KEY`, or switch `config.json` → `image-ocr.backend` to `chandra` |
| Chandra OCR cannot connect to vLLM | `image-ocr.backend=chandra` but `VLLM_API_BASE` is not reachable | Start your Chandra/vLLM server or update `VLLM_API_BASE` |
| Unsave button does nothing | not on `/saved`, or the file picker was cancelled | Switch the tab back to `https://www.threads.com/saved`, click the button and pick the file again |
| `probe` reports autosave not bound | Current browser session has not granted the `catch.json` autosave handle | Click **設定自動存檔** in the panel and pick `data/catch.json`, then re-run probe |
| `scrape` exits 2 with timeout | Scrape still running (large backlog) or panel stalled | Increase `--wait-seconds`; check panel status with `python scripts/agent_driver.py status` |
| `catch.json` stays 0 bytes after scrape | Autosave handle not bound | Re-grant via 設定自動存檔, then re-run scrape |
