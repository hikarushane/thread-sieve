# ThreadSieve

[English](README.md)

ThreadSieve 是一套本機端自動化流程，用來把 Threads 收藏貼文篩選、分類，轉成 markdown 筆記，並可自動取消儲存已整理過的 AI 貼文。

這個 repo 包含兩層：

- `userscripts/threads-scriber-auto.user.js`：瀏覽器端 Tampermonkey userscript，負責抓 Threads saved 頁面並寫出 `catch.json`。
- `scripts/*.py`：Python pipeline，負責分類、呼叫筆記產生器、圖片 OCR、agent-driven browser 操作。


---

## 流程概覽

```text
[Threads saved browser scrape] -> catch.json
                                  |
                                  v
                         scripts/watch_pipeline.py
                                  |
                    +-------------+-------------+
                    v                           v
      scripts/classify_to_scribe_ai.py   scripts/import_bookmarks_to_markdown.py
      (Gemini classifier)                (markdown note generator)
                    |                           |
                    v                           v
              unsave.json                 markdown notes
                    |                           |
                    +-------------+-------------+
                                  v
                  scripts/image_ocr_to_markdown.py
                  (image OCR -> ## 圖片文字)
                                  |
                                  v
              userscript auto-load unsave.json + auto-unsave
```

正常日常使用時，手動步驟只剩：

1. 開 watcher。
2. 在 Threads saved 頁面用 panel 觸發 scrape。

---

## 安裝

### Python 端

```powershell
cd path\to\threads-sieve
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

接著編輯 `.env`：

- 填入 `GEMINI_API_KEY`

接著編輯 `config.json`：

- 確認 `paths.catch-json`、`paths.unsave-json`、`paths.markdown-output-root`
- 填入 `paths.chrome-ws-cli`
- 依你的需求調整 `categories`、`unsaved-categories`、`hints`

ThreadSieve 已內建 markdown note generator (`scripts/import_bookmarks_to_markdown.py`)，不再呼叫外部 `PROJECT_threads-to-note` repo。markdown 筆記會寫到 `config.json` 的 `paths.markdown-output-root`，預設是 `output`。

### Browser 端

1. 用 `--remote-debugging-port=9222` 啟動 Chrome。
2. 打開 `https://www.threads.com/saved`。
3. 安裝 Tampermonkey。
4. 停用舊版 `threads-scriber.user.js`。
5. 安裝 `userscripts/threads-scriber-auto.user.js`。
6. Reload `/saved`。
7. 在 ThreadSieve panel 點 **設定自動存檔**，選 `data/catch.json`。
8. 在 Auto AI Sync panel 點 **綁定 unsave.json**，選 `data/unsave.json`。
9. 勾選 **自動載入 unsave.json** 和 **載入後自動取消儲存**。
10. 用下面指令確認：

```powershell
python scripts/agent_driver.py probe
```

成功時會看到 `OK: panel ready for agent-driven scrape`。

#### 用 remote debugging 啟動 Chrome

Chrome 136 之後，remote debugging 不能直接使用預設 Chrome profile，必須搭配非預設的 `--user-data-dir`。這個資料夾就是另一個 Chrome profile；Tampermonkey、userscript、Threads login cookie 都存在這裡。每次都用同一個 `--user-data-dir`，才不用一直重裝和重新登入。

啟動前先把所有 Chrome 視窗關掉，否則 Windows 可能沿用已經啟動、但沒有 `--remote-debugging-port=9222` 的 Chrome process。

```powershell
$profileDir = Join-Path $env:LOCALAPPDATA "ThreadSieve\ChromeDebugProfile"
New-Item -ItemType Directory -Force $profileDir | Out-Null
Start-Process "chrome.exe" -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=`"$profileDir`"",
  "https://www.threads.com/saved"
)
```

如果找不到 `chrome.exe`，改用完整路徑：

```powershell
Start-Process "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=`"$profileDir`"",
  "https://www.threads.com/saved"
)
```

確認 9222 port 有開：

```powershell
Invoke-WebRequest http://localhost:9222/json | Select-Object -Expand Content
```

看到一段 tabs JSON 就代表 `agent_driver.py` / `push_userscript.py` 可以連上。

---

## 日常使用 SOP

### Terminal A：啟動 watcher

```powershell
cd path\to\threads-sieve
.\start_pipeline.ps1
```

log 會輸出到 console 和 `pipeline.log`。停止時按 `Ctrl+C`。

### Terminal B：agent-driven scrape

先確認 panel ready：

```powershell
python scripts/agent_driver.py probe
```

觸發 scrape：

```powershell
python scripts/agent_driver.py scrape --cutoff 2010-01-01 --wait-seconds 300
```

只抓近期收藏時可縮小 cutoff：

```powershell
python scripts/agent_driver.py scrape --cutoff 2025-01-01 --wait-seconds 120
```

watcher 會在 `catch.json` 穩定後啟動：

1. `classify_to_scribe_ai.py`
2. 內建 markdown note generator (`scripts/import_bookmarks_to_markdown.py`)
3. `image_ocr_to_markdown.py`

圖片 OCR 只會對 `config.json` 裡 `image-ocr.trigger-categories` 指定的分類觸發，並把結果寫到 markdown 的 `## 圖片文字` 區塊。預設 OCR backend 是 Gemini；要切到 Chandra，改 `config.json` 的 `image-ocr.backend`。

---

## 補舊 markdown 的圖片 OCR

使用 `scripts/backfill_image_ocr.py` 補洞：當某些舊 markdown 筆記是在圖片 OCR 功能之前產生的，可以用這個 script 回頭補 `## 圖片文字`。它會使用 `config.json` 指定的 image OCR backend。

預設候選條件：

- frontmatter 有 `status: stub`
- frontmatter 有 `網址` 或 `url`
- 檔案尚未包含 `## 圖片文字`
- 去掉 frontmatter、`## Sources`、既有 `## 圖片文字` 後，正文長度低於 `--min-content-chars`，預設 `800`

先 dry-run 預覽整個資料夾：

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --dry-run
```

寫出 JSONL log：

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --log data/backfill-image-ocr.jsonl
```

每個被檢查的 `.md` 都會有一筆 JSONL event，狀態可能是：

- `processed`
- `skipped`
- `failed`
- `no_images`

單篇失敗是 soft failure，不會中斷整批。

### 依指定日期補洞

`backfill_image_ocr.py` 沒有內建「修改日期」參數。指定日期補洞不是常見批次模式，建議交給 agent 先用檔案系統篩選，再逐檔呼叫 script。

範例 prompt：

```text
Use `scripts/backfill_image_ocr.py`.

請先遞迴掃描：
<wiki-folder>

只挑選檔案系統 LastWriteTime 日期為 YYYY-MM-DD 的 `.md` 檔案，
再逐檔執行 `scripts/backfill_image_ocr.py --path "<file>"`。

不要直接把整個 wiki folder 丟給 script。
script 內建條件照預設即可：只處理 `status: stub`、內文不夠詳細、
frontmatter 有 `網址` 或 `url`、且沒有 `## 圖片文字` 的檔案。

請產生 JSONL log，最後回報 processed / skipped / failed / no_images summary。
```

如果只想先檢查候選檔，在 prompt 補一句：

```text
第一輪請加 `--dry-run`，只回報候選檔與 summary，不要修改 markdown。
```

---

## 設定

`config.json` 放非 secret 的通用設定、分類表和 OCR 行為：

| Key | Default | 用途 |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | classifier、watcher、userscript |
| `paths.unsave-json` | `data/unsave.json` | classifier、watcher、userscript |
| `paths.markdown-output-root` | `output` | markdown 筆記輸出 root；ThreadSieve 會寫入這裡，OCR 也會掃描這裡 |
| `paths.chrome-ws-cli` | required for browser automation | `agent_driver.py`、`push_userscript.py` 使用的 `chrome-ws` CLI |
| `categories` | project example list | Gemini classifier 可輸出的分類；開源使用者可依自己的分類表調整 |
| `unsaved-categories` | project example subset | 這些分類會輸出到 `unsave.json`，供 userscript 自動取消儲存 |
| `hints` | project example rules | 注入 Gemini prompt 的分類判斷補充 |
| `image-ocr` | 見下方 | 非 secret 的 OCR 行為設定 |

路徑可以用相對路徑或本機絕對路徑。Windows JSON 路徑建議用 forward slash：`C:/Users/<you>/...`。

舊的 `CATCH_PATH`、`UNSAVE_PATH`、`MARKDOWN_OUTPUT_PATH`、`THREADS_MARKDOWN_OUTPUT`、`CHROME_WS_PATH` 仍可作為相容覆寫，但新的設定請放在 `config.json`。

`.env` 常用欄位：

| Key | Default | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | required | classifier；若 `image-ocr.backend` 是 `gemini`，也用於圖片 OCR |
| `CLASSIFIER_MODEL` | `gemini-2.5-flash` | Gemini classifier model |
| `IMAGE_OCR_ENABLED` | `true` | watcher OCR step toggle |
| `IMAGE_OCR_MODEL` | `gemini-2.5-flash` | `image-ocr.backend=gemini` 時使用的 Gemini OCR model |
| `MODEL_CHECKPOINT` | `datalab-to/chandra-ocr-2` | `image-ocr.backend=chandra` 時的 Chandra model setting |
| `MAX_OUTPUT_TOKENS` | `12384` | Chandra max output tokens；可被 `image-ocr.max-output-tokens` 覆蓋 |
| `VLLM_API_BASE` | `http://localhost:8000/v1` | Chandra vLLM OpenAI-compatible endpoint |
| `VLLM_MODEL_NAME` | `chandra` | Chandra vLLM served model name |
| `VLLM_GPUS` | `0` | Chandra vLLM server GPU selection |
| `DEBOUNCE_SECONDS` | `2.0` | watcher debounce |
| `POLL_SECONDS` | `1.0` | watcher poll interval |

`config.json` 裡的 `image-ocr` 是非 secret 的 OCR 行為設定：

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

`backend` 可設為 `gemini` 或 `chandra`。使用 Chandra 時，`method=vllm` 會呼叫 `.env` 中 `VLLM_*` 指向的 OpenAI-compatible endpoint。`.env.example` 中的 Chandra 預設值來自 [datalab-to/chandra](https://github.com/datalab-to/chandra)；最新設定請以 upstream repo 為準。CLI 參數如 `--ocr-backend chandra` 和環境變數如 `IMAGE_OCR_BACKEND=chandra` 仍可作為單次 override。

---

## 測試

```powershell
cd path\to\threads-sieve
.\.venv\Scripts\Activate.ps1
pytest tests/
```

測試涵蓋：

- `classify_to_scribe_ai.py`
- `watch_pipeline.py`
- `image_ocr_to_markdown.py`，包含 OCR backend selection
- `backfill_image_ocr.py`

---

## 已知限制

- auto-unsave 需要瀏覽器停在 `/saved`。
- File System Access permission 可能在瀏覽器重啟後失效，需要重新綁定。
- markdown image OCR 會掃描 markdown root；若不想使用預設 `output`，請設定 `config.json` 的 `paths.markdown-output-root`。
- OCR 會用 Playwright render Threads post；若缺 browser binary，執行 `playwright install chromium`。
- Gemini quota 會被 classifier 和 note writer 消耗；如果 `image-ocr.backend=gemini`，OCR 也會消耗 Gemini quota。
- Chandra OCR 是 optional；若 `image-ocr.backend=chandra` 且 `method=vllm`，需要 `.env` 的 `VLLM_API_BASE` 指向可連線的 Chandra/vLLM server。
- Chandra CLI 仍需要可用 backend：`chandra --method vllm` 是 client，仍要有 vLLM server；`chandra --method hf` 是本機模型，但 Chandra OCR 2 會下載 10GB+ 模型，在低資源 Windows 機器上可能非常慢或失敗。沒有合適 Chandra backend 時，請使用 Gemini OCR。

---

## Troubleshooting

| 現象 | 可能原因 | 處理方式 |
| --- | --- | --- |
| watcher 顯示 missing required config | `config.json` 路徑空白 | 檢查 `paths.catch-json` 和 `paths.unsave-json` |
| `catch.json` 寫入但 watcher 沒動 | mtime 落在 debounce window | 等 `DEBOUNCE_SECONDS` 或調小 `POLL_SECONDS` |
| classifier 顯示 `GEMINI_API_KEY missing` | subprocess 沒拿到 env | 確認 key 在 `.env`，重啟 watcher |
| OCR 顯示 `GEMINI_API_KEY missing` | `image-ocr.backend=gemini` 但沒有 key | 設定 `GEMINI_API_KEY`，或把 `config.json` 的 `image-ocr.backend` 改成 `chandra` |
| Chandra OCR 連不到 vLLM | `image-ocr.backend=chandra` 但 `VLLM_API_BASE` 不可連線 | 啟動 Chandra/vLLM server，或修正 `VLLM_API_BASE` |
| panel 沒載入 AI classification | handle 未綁定或 autoLoad 關閉 | 重新綁定 `unsave.json`，勾選自動載入 |
| `probe` 說 autosave not bound | FS Access permission 掉了 | 重新點 **設定自動存檔** |
| `scrape` timeout | backlog 太大或 panel 卡住 | 增加 `--wait-seconds`，用 `agent_driver.py status` 檢查 |
