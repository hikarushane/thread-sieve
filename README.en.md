# ThreadSieve (lite)

[繁體中文](README.md)

> **Latest update (2026-07-18)**: browser panel redesign — the manual-tools section and the Auto AI Sync panel are gone, replaced by a single big **取消儲存** (unsave) button that re-picks `unsave.json` on every run, eliminating accidental runs against stale classification results; install is now a one-line command; new macOS double-click launcher. Full history in [RELEASE_NOTES.md](RELEASE_NOTES.md).

> End-user branch: no `superpowers-chrome`, no watcher, no Chrome debug port.  
> For the full automation build (terminal watcher + agent-driven scrape + Chandra OCR), switch to the `full` branch.

The problem with Threads bookmarks:

  ❌ saved hundreds of posts
  ❌ zero categories
  ❌ can't find anything
  ❌ they just sit there rotting

ThreadSieve is a local automation pipeline that turns Threads saved posts into categorized markdown notes, and unsaves posts in specified categories with a one-button flow.

Post content passed into classification and note generation includes the main post text, comments from the post author in the same thread, and text extracted from post images with OCR. When the saved item is a reply, the note also carries the reply's single-line ancestor context (the full chain from the root post down to the reply) and a reply section (the original poster's replies plus substantive comments, rendered collapsed).

Two layers:

- `userscripts/threads-scriber-auto.user.js` — Tampermonkey userscript; scrapes the Threads saved page and writes `catch.json`.
- `scripts/*.py` — Python pipeline; LLM classification, markdown notes, image OCR.

---

## What it does

![ThreadSieve flow overview](docs/flow-overview.png)

---

## Prerequisites

| Requirement | Why |
| --- | --- |
| Python 3.10+ (not needed for the one-line install — uv downloads 3.12 automatically) | classifier, markdown generator, image OCR |
| Google Chrome / Edge | browser |
| Tampermonkey extension | userscript injection |
| LLM API key (one of Gemini / Anthropic / OpenAI; Gemini by default) | classification + titles + image OCR |

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
| `paths.catch-json` | Path to `data/catch.json` |
| `paths.unsave-json` | Path to `data/unsave.json` |
| `paths.markdown-output-root` | Where markdown notes are written (default: `output`) |
| `categories` | Ordered list of categories the classifier can output |
| `unsaved-categories` | Subset of `categories` whose posts get added to `unsave.json` |
| `hints` | Free-text rules injected into the classifier prompt for edge cases |
| `llm.provider` (optional) | `gemini` (default) / `anthropic` / `openai` |

`category-overrides` is optional — keyword/regex rules that force a category before calling the LLM.

### 2. Browser side (one-time setup)

1. Open Chrome / Edge and navigate to `https://www.threads.com/saved`.
2. Install [Tampermonkey](https://www.tampermonkey.net/).
3. Install `userscripts/threads-scriber-auto.user.js`.
4. Reload the `/saved` tab. The **ThreadSieve** panel appears.

---

## Daily SOP

#### Step 1 · Prepare the browser

1. Open Chrome and navigate to `https://www.threads.com/saved`.
2. If needed, reload `/saved`.
3. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.

> File System Access grants may need to be re-done each browser session.

#### Step 2 · Scrape via the panel

1. Enter a cutoff date in the ThreadSieve panel date input.
2. Click **清空結果** to clear leftover results.
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

Fallback for shell users:

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

## Backfill existing markdown image OCR

Use `scripts/backfill_image_ocr.py` when older markdown notes were written before image OCR existed. The tool scans a markdown file or folder, finds likely OCR-missing stubs, fetches the Threads post images, OCRs them with Gemini, and inserts `## 圖片文字` before `## Sources`.

Default candidate rules:

- frontmatter has `status: stub`
- frontmatter has `網址` or `url`
- the note does not already contain `## 圖片文字`
- non-frontmatter body is shorter than `--min-content-chars` (default: `800`)

Preview a folder without fetching images or editing files:

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --dry-run
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

`config.json`:

| Key | Default | Used by |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | userscript writes, classify reads |
| `paths.unsave-json` | `data/unsave.json` | classify writes, userscript reads |
| `paths.markdown-output-root` | `output` | markdown note root |
| `categories` | example list | classifier output categories |
| `unsaved-categories` | example subset | posts in these categories are written to `unsave.json` |
| `category-overrides` | `[]` | optional keyword/regex forced categories |
| `hints` | example rules | classifier prompt nudges |
| `llm.provider` | `gemini` | LLM provider: `gemini` / `anthropic` / `openai` |
| `llm.text-model` / `title-model` / `vision-model` | provider default | per-stage model overrides (leave unset for provider defaults) |
| `image-ocr.backend` | `gemini` | lite build only supports Gemini |
| `image-ocr.trigger-categories` | `["AI"]` | categories that trigger image OCR |
| `thread-context.enabled` | `true` | ancestor/replies capture toggle; `false` restores the previous behavior |
| `thread-context.min-reply-chars` | `12` | minimum comment length for the reply section (the original poster's replies are exempt) |
| `thread-context.max-replies` | `30` | maximum reply *threads* kept (one thread may contain several messages; the original poster's replies are always kept and don't count toward the cap; extras are truncated, noted in the callout header) |

Path values may be relative or absolute. For Windows absolute paths in JSON you MUST use forward slashes (`C:/Users/<you>/...`) or escape every backslash as `\\` (`C:\\Users\\<you>\\...`). A single `\` is the JSON escape character, so `"D:\shane\..."` raises `json.decoder.JSONDecodeError: Invalid \escape`.

`.env`:

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

The pipeline writes a `threads_events.jsonl` event log into the output directory; ancestor/replies capture outcomes are logged as `reply_fetch_fetched_structured` (structured parse succeeded) and `reply_fetch_fetched_fallback` (fell back to plain-text parsing) events.

---

## Known limitations

- **Browser must be on `/saved`** to run the unsave pass (the button reports an error otherwise). The classify step still writes `unsave.json` and markdown regardless.
- **File System Access grants are per-run setup**. Re-pick `catch.json` for autosave if the panel loses the grant; `unsave.json` is re-picked on every unsave run by design.
- **LLM quota**: each classify run classifies every post once, then calls the LLM again for title generation and (when triggered) image OCR — all from the same API key.
- **Playwright is required for image OCR**: if browser binaries are missing, run `playwright install chromium`.
- **The reply section only captures anonymously visible replies**: deeply nested replies and content behind the login wall are not collected.
- **Threads redesigns may break the embedded-data parse**: the pipeline then falls back to the previous plain-text parsing (that note temporarily has no ancestor/reply sections; the main content is unaffected), and `saved_kind` is a best-effort `root`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Double-clicking `run_classify.cmd`/`run_classify.command` shows `.venv not found` | venv never created | Run the one-line install once (pick the command for your OS) |
| classify exits with `json.decoder.JSONDecodeError: Invalid \escape` | Windows path in `config.json` uses single `\` | Use `/` (`D:/foo/bar`) or `\\` (`D:\\foo\\bar`) |
| classify exits with `<PROVIDER>_API_KEY missing` | the selected provider's key not in `.env`, or venv didn't pick it up | Confirm the matching `..._API_KEY=...` in `.env`, double-click again |
| Unsave button does nothing | not on `/saved`, or the file picker was cancelled | Switch the tab back to `https://www.threads.com/saved`, click the button and pick the file again |

---

## Want more automation?

Switch to the `full` branch for:

- `watch_pipeline.py` — auto-trigger classify on `catch.json` change.
- `agent_driver.py` — drive the panel from terminal via `superpowers-chrome` + Chrome `--remote-debugging-port=9222`.
- Terminal B confirmation gate — every unsave prints candidates and asks `y/n`.
- Chandra / vLLM image OCR backend.

Cost: Node.js, Claude Code + `superpowers-chrome` plugin, Chrome debug profile setup, additional hook checks.
