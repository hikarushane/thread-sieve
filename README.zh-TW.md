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
                                  v
             scripts/import_bookmarks_to_markdown.py
             (分類一次 -> markdown notes + unsave.json)
                                  |
                                  v
                  scripts/image_ocr_to_markdown.py
                  (image OCR -> ## 圖片文字)
                                  |
                                  v
              userscript auto-load unsave.json + confirmed auto-unsave
```

完成安裝後，日常使用通常依照下面順序進行：

1. 在 Terminal A 啟動 watcher。
2. 在 Chrome 的 Threads saved 頁面重新授權 `catch.json`、重新綁定 `unsave.json`。
3. 用 panel 或 `agent_driver.py scrape` 觸發 scrape。
4. 在 Terminal B 檢查 `unsave.json` 候選，輸入 `y` 或 `n` 確認是否取消儲存。

---

## 前置需求

| 需求 | 用途 |
| --- | --- |
| Python 3.11+ | watcher、classifier、markdown note generator |
| Node.js 18+ | 執行 `chrome-ws` CLI |
| Google Chrome / Edge | 透過 Chrome DevTools Protocol 操作 browser |
| Tampermonkey extension | 載入 Threads saved 頁面的 userscript |
| Claude Code + [`superpowers-chrome`](https://github.com/obra/superpowers-chrome) plugin | 提供 `agent_driver.py` 和 `push_userscript.py` 需要的 `chrome-ws` CLI |

---

## 安裝

### 0. `superpowers-chrome`（`agent_driver.py` 必要）

`agent_driver.py` 會透過 [`superpowers-chrome`](https://github.com/obra/superpowers-chrome) plugin 附帶的 `chrome-ws` Node.js CLI 控制已登入的 Chrome。設定 `--remote-debugging-port=9222` 之前，請先確認這個 CLI 已安裝並寫進 `config.json`。

#### A. 安裝 plugin

在 Claude Code 中，從 `obra/superpowers-marketplace` marketplace 安裝 `superpowers-chrome`：

```text
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers-chrome@superpowers-marketplace
```

安裝後，`chrome-ws` CLI 通常會在類似下面的位置；實際版本號請以你本機安裝的目錄為準。

```text
C:\Users\<you>\.claude\plugins\cache\superpowers-marketplace\superpowers-chrome\2.1.0\skills\browsing\chrome-ws
```

確認 Node.js 可以執行它：

```powershell
node "C:\Users\<you>\.claude\plugins\cache\superpowers-marketplace\superpowers-chrome\2.1.0\skills\browsing\chrome-ws" --help
```

#### B. 設定 `config.json`

`agent_driver.py` 和 `push_userscript.py` 都需要 `chrome-ws` CLI 路徑。請在 `config.json` 設定：

```json
"paths": {
  "chrome-ws-cli": "C:/Users/<you>/.claude/plugins/cache/superpowers-marketplace/superpowers-chrome/2.1.0/skills/browsing/chrome-ws"
}
```

舊的 `CHROME_WS_PATH` 環境變數仍可作為相容覆寫；新的安裝建議使用 `config.json`。

#### C. 用 remote debugging 啟動 Chrome

執行任何 `agent_driver.py` 指令之前，Chrome 必須先用 `--remote-debugging-port=9222` 啟動。

`superpowers-chrome` 也可以用 `chrome-ws start` 啟動 Chrome，但預設行為可能會選擇動態 port。ThreadSieve 的 scripts 和本機 hook 目前都預期使用 `9222`，所以建議使用下面的固定 port 啟動方式。如果你改用 `chrome-ws start`，請用 `--port=9222` 或 `CHROME_WS_PORT=9222` 固定 port。

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

日常使用時也可以做一個專用捷徑：

1. 複製桌面或工作列上的 Chrome 捷徑。
2. 右鍵 -> 內容 -> 目標，在原本內容後面加上 ` --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ThreadSieve\ChromeDebugProfile" https://www.threads.com/saved`。
3. 以後都用這個捷徑開啟 Chrome，並在這個 debug profile 裡安裝 Tampermonkey、登入 Threads。

```text
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ThreadSieve\ChromeDebugProfile" https://www.threads.com/saved
```

確認 9222 port 有開：

```powershell
Invoke-WebRequest http://localhost:9222/json | Select-Object -Expand Content
```

看到一段 tabs JSON 就代表 `agent_driver.py` / `push_userscript.py` 可以連上。

#### D. Agent hooks 會檢查這個前置條件

這個 repo 內建 Claude Code 和 Codex 的本機 hook：

- `.claude/settings.json` 會在 Claude Code shell command 前執行 `.claude/hooks/check-chrome-debug.ps1`。
- `.codex/hooks.json` 會透過 `.codex/check-chrome-debug.cmd` 執行 `.codex/check-chrome-debug.ps1`。

這兩個 hook 只攔截 `agent_driver.py` 和 `push_userscript.py`。如果 `127.0.0.1:9222` 連不上，它們會阻止指令繼續執行，避免 agent 誤開沒有 debug port 的新 browser 或改成手動操作 Tampermonkey。

---

### 1. Python 端

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

### 2. Browser 端（一次性設定）

1. 使用上方設定好的 debug profile 啟動 Chrome，並確認帶有 `--remote-debugging-port=9222`。
2. 打開 `https://www.threads.com/saved`，並保持這個 tab 開著。
3. 在這個 Chrome profile 安裝 Tampermonkey。
4. 如果你曾在同一個 Tampermonkey profile 安裝過 `threads-scriber.user.js`，請先停用它；第一次安裝 ThreadSieve 可略過這步。
5. 安裝 `userscripts/threads-scriber-auto.user.js`。
6. Reload `/saved`。右下角會出現 **ThreadSieve · Auto AI Sync** panel。

`catch.json` 自動存檔授權、`unsave.json` 綁定、以及 `agent_driver.py probe` 檢查放在日常使用 SOP。Chrome 的 File System Access handle 可能需要每次重新授權，第一次安裝時不用把它視為永久設定。

---

## 日常使用 SOP

### Terminal A：啟動 watcher

```powershell
cd path\to\threads-sieve
.\start_pipeline.ps1
```

log 會輸出到 console 和 `pipeline.log`。停止時按 `Ctrl+C`。

### Terminal B：agent-driven scrape

先準備 browser 端：

1. 用安裝階段設定好的同一個 debug profile 啟動 Chrome，並帶上 `--remote-debugging-port=9222`。
2. 開啟 `https://www.threads.com/saved`，並保持這個 tab 開著。
3. 如果 panel 還沒出現，先 reload `/saved`，讓 **ThreadSieve panel** 和 **Auto AI Sync panel** 載入。
4. 在 ThreadSieve panel 點 **設定自動存檔**，選 `data/catch.json`。
5. 在 Auto AI Sync panel 點 **綁定 unsave.json**，選 `data/unsave.json`。
6. 勾選 **自動載入 unsave.json**。
7. 若要使用 Terminal B 的確認 gate，**載入後自動取消儲存** 請不要勾；`agent_driver.py scrape` 會在你輸入 `y` 後執行一次性取消儲存。
8. 可點 **立即檢查** 強制載入一次 AI classification；成功後小型 Auto AI Sync panel 會收合，避免遮住主 panel。

再確認 panel ready：

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

預設 scrape 會啟用 Terminal B confirmation gate：先停用 browser auto-unsave，等 watcher 寫出新的 `unsave.json`，把候選印成 `作者:<author>| 貼文:<first sentence>` 並問 `確認執行?(y/n)`。輸入 `y` 才會 force-load `unsave.json` 並執行一次性取消儲存；輸入 `n` 會保留 `unsave.json` 不動，browser auto-unsave 也維持關閉。

若要略過人工確認，讓 browser 在 `unsave.json` 更新後直接取消儲存，加上 `--no-unsave-confirm`。`--unsave-timeout-seconds`（預設 `600`）控制 gate 等待新 `unsave.json` 的最長秒數。

watcher 會在 `catch.json` 穩定後啟動 notes workflow。這條路徑會對每篇貼文分類一次，並用同一批分類結果寫出 markdown 筆記和 `unsave.json`：

1. 內建 markdown note generator (`scripts/import_bookmarks_to_markdown.py`)
2. `image_ocr_to_markdown.py`

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
| `paths.catch-json` | `data/catch.json` | watcher、note workflow、userscript |
| `paths.unsave-json` | `data/unsave.json` | note workflow、OCR、watcher、userscript |
| `paths.markdown-output-root` | `output` | markdown 筆記輸出 root；ThreadSieve 會寫入這裡，OCR 也會掃描這裡 |
| `paths.chrome-ws-cli` | required for browser automation | `agent_driver.py`、`push_userscript.py` 使用的 `chrome-ws` CLI |
| `categories` | project example list | Gemini classifier 可輸出的分類；開源使用者可依自己的分類表調整 |
| `unsaved-categories` | project example subset | 這些分類會輸出到 `unsave.json`，供 userscript 自動取消儲存 |
| `category-overrides` | `[]` | 可選的 keyword / regex 強制分類規則；適合放個人 taxonomy 規則 |
| `hints` | project example rules | 注入 Gemini prompt 的分類判斷補充 |
| `image-ocr` | 見下方 | 非 secret 的 OCR 行為設定 |

路徑可以用相對路徑或本機絕對路徑。Windows JSON 路徑建議用 forward slash：`C:/Users/<you>/...`。

`category-overrides` 範例：

```json
"category-overrides": [
  {
    "category": "Project",
    "keywords": ["project mercury"],
    "regex": ["#project\\b"]
  }
]
```

正常 watcher 路徑會在 `scripts/import_bookmarks_to_markdown.py` 裡分類一次，再用同一批分類結果寫出 markdown 筆記和 `unsave.json`。`scripts/classify_to_scribe_ai.py` 仍保留作為 standalone 相容/除錯指令；它的 CLI-only `--unsaved-categories` 覆寫只影響那次 standalone run。

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

- `classify_to_scribe_ai.py` standalone 相容分類輸出
- `import_bookmarks_to_markdown.py` 單次分類同時供 markdown 和 `unsave.json` 使用
- `watch_pipeline.py`
- `image_ocr_to_markdown.py`，包含 OCR backend selection
- `backfill_image_ocr.py`

---

## 已知限制

- auto-unsave 需要瀏覽器停在 `/saved`。
- File System Access 授權視為每次日常使用前的準備步驟；若 browser 顯示 handle 未綁定，請重新選檔。
- markdown image OCR 會掃描 markdown root；若不想使用預設 `output`，請設定 `config.json` 的 `paths.markdown-output-root`。
- OCR 會用 Playwright render Threads post；若缺 browser binary，執行 `playwright install chromium`。
- Gemini quota：每次 scrape 會對每篇貼文分類一次，接著為 markdown title generation 再呼叫 Gemini；如果 `image-ocr.backend=gemini`，OCR 也會消耗 Gemini quota。
- Chandra OCR 是 optional；若 `image-ocr.backend=chandra` 且 `method=vllm`，需要 `.env` 的 `VLLM_API_BASE` 指向可連線的 Chandra/vLLM server。
- Chandra CLI 仍需要可用 backend：`chandra --method vllm` 是 client，仍要有 vLLM server；`chandra --method hf` 是本機模型，但 Chandra OCR 2 會下載 10GB+ 模型，在低資源 Windows 機器上可能非常慢或失敗。沒有合適 Chandra backend 時，請使用 Gemini OCR。

---

## Troubleshooting

| 現象 | 可能原因 | 處理方式 |
| --- | --- | --- |
| watcher 顯示 missing required config | `config.json` 路徑空白 | 檢查 `paths.catch-json` 和 `paths.unsave-json` |
| `catch.json` 寫入但 watcher 沒動 | mtime 落在 debounce window | 等 `DEBOUNCE_SECONDS` 或調小 `POLL_SECONDS` |
| notes workflow 顯示 `GEMINI_API_KEY missing` | subprocess 沒拿到 env | 確認 key 在 `.env`，重啟 watcher |
| OCR 顯示 `GEMINI_API_KEY missing` | `image-ocr.backend=gemini` 但沒有 key | 設定 `GEMINI_API_KEY`，或把 `config.json` 的 `image-ocr.backend` 改成 `chandra` |
| Chandra OCR 連不到 vLLM | `image-ocr.backend=chandra` 但 `VLLM_API_BASE` 不可連線 | 啟動 Chandra/vLLM server，或修正 `VLLM_API_BASE` |
| panel 沒載入 AI classification | handle 未綁定或 autoLoad 關閉 | 重新綁定 `unsave.json`，勾選自動載入 |
| `probe` 說 autosave not bound | 本次 browser session 尚未授權 `catch.json` | 重新點 **設定自動存檔** |
| `scrape` timeout | backlog 太大或 panel 卡住 | 增加 `--wait-seconds`，用 `agent_driver.py status` 檢查 |
