# ThreadSieve (lite)

[繁體中文](README.md)

> End-user branch: no `superpowers-chrome`, no watcher, no Chrome debug port.  
> For the full automation build (terminal watcher + agent-driven scrape + Chandra OCR), switch to the `main` branch.

The problem with Threads bookmarks:

  ❌ saved hundreds of posts
  ❌ zero categories
  ❌ can't find anything
  ❌ they just sit there rotting

ThreadSieve is a local automation pipeline that turns Threads saved posts into categorized markdown notes, and auto-unsaves posts in specified categories.

Post content passed into classification and note generation includes the main post text, comments from the post author in the same thread, and text extracted from post images with OCR.

Two layers:

- `userscripts/threads-scriber-auto.user.js` — Tampermonkey userscript; scrapes the Threads saved page and writes `catch.json`.
- `scripts/*.py` — Python pipeline; classification, markdown notes, Gemini image OCR.

---

## What it does

```
[Threads /saved (browser-panel scrape)] -> catch.json
                                            |
                                            v
                              double-click run_classify.cmd
                                            |
                                            v
                 scripts/import_bookmarks_to_markdown.py
                 (classify once -> markdown notes + unsave.json)
                                            |
                                            v
                    scripts/image_ocr_to_markdown.py
                    (Gemini OCR -> ## 圖片文字)
                                            |
                                            v
                  userscript: auto-load unsave.json + confirmed unsave
```

---

## Prerequisites

| Requirement | Why |
| --- | --- |
| Python 3.11+ | classifier, markdown generator, image OCR |
| Google Chrome / Edge | browser |
| Tampermonkey extension | userscript injection |
| Gemini API key | classification + image OCR |

No Node.js. No `--remote-debugging-port`. No Claude Code plugin required.

---

## Install

### 0. Clone the repo

```powershell
git clone -b lite https://github.com/hikaru-yeh/thread-sieve.git
cd thread-sieve
```

### 1. Python side

```powershell
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
| `paths.catch-json` | Path to `data/catch.json` |
| `paths.unsave-json` | Path to `data/unsave.json` |
| `paths.markdown-output-root` | Where markdown notes are written (default: `output`) |
| `categories` | Ordered list of categories the classifier can output |
| `unsaved-categories` | Subset of `categories` whose posts get added to `unsave.json` |
| `hints` | Free-text rules injected into the Gemini prompt for edge cases |

`category-overrides` is optional — keyword/regex rules that force a category before calling Gemini.

### 2. Browser side (one-time setup)

1. Open Chrome / Edge and navigate to `https://www.threads.com/saved`.
2. Install [Tampermonkey](https://www.tampermonkey.net/).
3. Install `userscripts/threads-scriber-auto.user.js`.
4. Reload the `/saved` tab. A floating panel "ThreadSieve · Auto AI Sync" appears bottom-right.

---

## Daily SOP (no typing)

#### Step 1 · Prepare the browser

1. Open Chrome and navigate to `https://www.threads.com/saved`.
2. If needed, reload `/saved`.
3. In the **ThreadSieve panel**: click **設定自動存檔** → pick `data/catch.json`.
4. In the **Auto AI Sync panel**: click **綁定 unsave.json** → pick `data/unsave.json`.
5. Tick **自動載入 unsave.json**.

> File System Access grants may need to be re-done each browser session.

#### Step 2 · Scrape via the panel

1. Enter a cutoff date in the ThreadSieve panel date input.
2. Click **清空結果** to clear leftover results.
3. Click **開始抓取** and wait for `狀態` to show `完成` or `待機中`.

#### Step 3 · Run classify

Double-click `run_classify.cmd` in the project root. A console window opens, activates `.venv`, runs `scripts/import_bookmarks_to_markdown.py`, then prints `[DONE]` or `[FAILED]` and waits for any key.

Optional desktop shortcut: right-click `run_classify.cmd` → Send to → Desktop (create shortcut). Then double-click the shortcut from anywhere.

This classifies every post once and writes both markdown notes and `unsave.json`. Image OCR runs automatically for posts whose category matches `config.json` → `image-ocr.trigger-categories`.

Fallback for shell users:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/import_bookmarks_to_markdown.py
```

#### Step 4 · Confirm unsave in the browser

The Auto AI Sync panel polls `unsave.json` every 3 s. Once it loads the new file it shows the candidate count and `generatedAt` timestamp.

- Click **立即檢查** to force an immediate poll.
- Tick **載入後自動取消儲存** before the file updates, or click the unsave button manually, to unsave the AI candidates.

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

## Configuration

`config.json`:

| Key | Default | Used by |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | userscript writes, classify reads |
| `paths.unsave-json` | `data/unsave.json` | classify writes, userscript reads |
| `paths.markdown-output-root` | `output` | markdown note root |
| `categories` | example list | classifier output categories |
| `unsaved-categories` | example subset | maps to `decision="ai"` → auto-unsave |
| `category-overrides` | `[]` | optional keyword/regex forced categories |
| `hints` | example rules | Gemini prompt nudges |
| `image-ocr.backend` | `gemini` | lite build only supports Gemini |
| `image-ocr.trigger-categories` | `["AI"]` | categories that trigger image OCR |

Path values may be relative or absolute. For Windows paths in JSON, forward slashes are easiest: `C:/Users/<you>/...`.

`.env`:

| Key | Default | Used by |
| --- | --- | --- |
| `GEMINI_API_KEY` | required | classifier + image OCR |
| `CLASSIFIER_MODEL` | `gemini-2.5-flash` | classifier |
| `IMAGE_OCR_ENABLED` | `true` | OCR step toggle |
| `IMAGE_OCR_MODEL` | `gemini-2.5-flash` | Gemini image OCR model |

---

## Known limitations

- **Browser must be on `/saved`** for auto-unsave to fire. The classify step still writes `unsave.json` and markdown regardless.
- **File System Access grants are per-run setup**. Re-bind `catch.json` / `unsave.json` if the panel shows "handle: not bound".
- **Gemini quota**: each scrape classifies every post once, then uses Gemini again for title generation and (when triggered) image OCR — all from the same key.
- **Playwright is required for image OCR**: if browser binaries are missing, run `playwright install chromium`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Double-clicking `run_classify.cmd` shows `.venv not found` | venv never created | Run the install → Python side block once |
| classify exits with `GEMINI_API_KEY missing` | key not in `.env` or venv didn't pick it up | Confirm `GEMINI_API_KEY=...` in `.env`, double-click again |
| Panel never loads AI classification | handle not bound / autoLoad off | Re-bind `unsave.json`, tick **自動載入 unsave.json** |
| `unsave.json` updated but browser idle | Auto AI Sync poll not yet cycled | Click **立即檢查** to force a poll |
| Unsave button does nothing | not on `/saved` | Switch the tab back to `https://www.threads.com/saved` |

---

## Want more automation?

Switch to the `main` branch for:

- `watch_pipeline.py` — auto-trigger classify on `catch.json` change.
- `agent_driver.py` — drive the panel from terminal via `superpowers-chrome` + Chrome `--remote-debugging-port=9222`.
- Terminal B confirmation gate — every unsave prints candidates and asks `y/n`.
- Chandra / vLLM image OCR backend.

Cost: Node.js, Claude Code + `superpowers-chrome` plugin, Chrome debug profile setup, additional hook checks.
