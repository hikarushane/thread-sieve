# ThreadSieve (lite)

[English](README.en.md)

> 一般使用者版本：免裝 superpowers-chrome、免開 watcher、免 Chrome debug port。  
> 完整自動化版本（terminal watcher + agent-driven scrape + Chandra OCR）請切到 `full` 分支。

Threads 收藏貼文的問題：

  ❌ 存了幾百篇
  ❌ 沒有分類
  ❌ 找不到
  ❌ 最後全部爛在那裡

ThreadSieve 是一套本機端自動化流程，把 Threads 收藏貼文篩選、分類，轉成 markdown 筆記，並自動取消儲存指定分類的貼文。

抓取後進入分類與筆記產生的貼文內容包含：主文內容、作者在同串貼文中的留言，以及貼文圖片經 OCR 轉出的文字。若收藏的是某則回應，筆記還會附上該回應的單線上文脈絡（母帖到回應的完整一條線）與回覆區（原帖作者的回覆與有內容的留言，摺疊呈現）。

兩層：

- `userscripts/threads-scriber-auto.user.js`：Tampermonkey userscript，抓 Threads saved 頁面寫出 `catch.json`。
- `scripts/*.py`：Python pipeline，分類、寫 markdown、Gemini 圖片 OCR。

---

## 流程概覽

```text
[Threads /saved (瀏覽器 panel scrape)] -> catch.json
                                            |
                                            v
                  雙擊 run_classify.cmd / .command
                                            |
                                            v
                 scripts/import_bookmarks_to_markdown.py
                 (分類一次 -> markdown notes + unsave.json)
                                            |
                                            v
                    scripts/image_ocr_to_markdown.py
                    (Gemini OCR -> ## 圖片文字)
                                            |
                                            v
                  userscript 自動載入 unsave.json + 確認 unsave
```

---

## 前置需求

| 需求 | 用途 |
| --- | --- |
| Python 3.11+ | classifier + markdown 產生器 + 圖片 OCR |
| Google Chrome / Edge | 瀏覽器 |
| Tampermonkey extension | 載入 userscript |
| Gemini API key | 分類 + 圖片 OCR |

---

## 安裝

### 0. Clone 此 repo

```powershell
git clone -b lite https://github.com/hikaru-yeh/thread-sieve.git
cd thread-sieve
```

### 1. Python 端

**Windows（PowerShell）：**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
copy config.json.example config.json
```

**macOS（Terminal）：**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
cp config.json.example config.json
```

編輯 `.env`：填入 `GEMINI_API_KEY`。

編輯 `config.json`：

| Key | 要填什麼 |
| --- | --- |
| `paths.catch-json` | `data/catch.json` 的路徑（相對或絕對） |
| `paths.unsave-json` | `data/unsave.json` 的路徑（相對或絕對） |
| `paths.markdown-output-root` | markdown 筆記輸出目錄（預設 `output`） |
| `categories` | Gemini classifier 可輸出的分類清單（依優先順序排列） |
| `unsaved-categories` | `categories` 的子集；這些分類的貼文會寫入 `unsave.json` |
| `hints` | 注入 Gemini prompt 的判斷補充說明，用於邊界情境 |

`category-overrides` 是可選欄位，可設定關鍵字或 regex 規則，在呼叫 Gemini 前強制指定分類。

### 2. Browser 端（一次性設定）

1. 打開 Chrome 或 Edge，前往 `https://www.threads.com/saved`。
2. 安裝 [Tampermonkey](https://www.tampermonkey.net/)。
3. 安裝 `userscripts/threads-scriber-auto.user.js`。
4. Reload `/saved`。右下角會出現 **ThreadSieve · Auto AI Sync** panel。

---

## 日常 SOP

#### 步驟 1：準備瀏覽器

1. 開啟 Chrome，前往 `https://www.threads.com/saved`。
2. 如果 panel 還沒出現，先 reload `/saved`。
3. 在 ThreadSieve panel 點 **設定自動存檔**，選 `data/catch.json`。
4. 在 Auto AI Sync panel 點 **綁定 unsave.json**，選 `data/unsave.json`。
5. 勾選 **自動載入 unsave.json**。

> File System Access 授權每個 browser session 可能要重做一次。

#### 步驟 2：用 panel 觸發 scrape

1. 在 ThreadSieve panel 的日期欄輸入截止日期。
2. 點 **清空結果** 清除上次的殘留。
3. 點 **開始抓取**，等 `狀態` 顯示 `完成` 或 `待機中`。

#### 步驟 3：執行 classify

- **Windows**：雙擊專案根目錄的 `run_classify.cmd`。
- **macOS**：雙擊專案根目錄的 `run_classify.command`（首次可能需 `chmod +x run_classify.command`，或右鍵 → 打開以繞過 Gatekeeper）。

會跳出一個 console／Terminal 視窗，自動 activate `.venv` 並執行 `scripts/import_bookmarks_to_markdown.py`，結束時顯示 `[DONE]` 或 `[FAILED]`，按任意鍵關閉。

若想做桌面捷徑：

- **Windows**：右鍵 `run_classify.cmd` → 傳送到 → 桌面（建立捷徑）。
- **macOS**：對 `run_classify.command` 按 ⌥⌘ 拖到桌面建立替身（alias）。

之後雙擊捷徑即可。

這支 script 對每篇貼文分類一次，並用同一批分類結果寫出 markdown 筆記和 `unsave.json`。若分類結果符合 `config.json` → `image-ocr.trigger-categories`，圖片 OCR 也會自動執行。

備案：偏好用指令列：

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

#### 步驟 4：在瀏覽器確認 unsave

Auto AI Sync panel 每 3 秒 poll 一次 `unsave.json`。載入新檔案後會顯示候選筆數和 `generatedAt`。

- 點 **立即檢查** 強制立即 poll。
- 在檔案更新前勾選 **載入後自動取消儲存**，或手動點取消儲存按鈕，執行 AI 貼文取消儲存。

---

## 補舊 markdown 的圖片 OCR

使用 `scripts/backfill_image_ocr.py` 補洞：當某些舊 markdown 筆記是在圖片 OCR 功能之前產生的，可以用這個 script 回頭補 `## 圖片文字`。

預設候選條件：

- frontmatter 有 `status: stub`
- frontmatter 有 `網址` 或 `url`
- 檔案尚未包含 `## 圖片文字`
- 去掉 frontmatter、`## Sources`、既有 `## 圖片文字` 後，正文長度低於 `--min-content-chars`（預設 `800`）

先 dry-run 預覽：

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --dry-run
```

寫出 JSONL log：

```powershell
python scripts/backfill_image_ocr.py --path "<wiki-folder>" --log data/backfill-image-ocr.jsonl
```

每個被檢查的 `.md` 都會有一筆 JSONL event：`processed` / `skipped` / `failed` / `no_images`。單篇失敗是 soft failure，不會中斷整批。

---

## LLM provider 選擇

ThreadSieve 的分類、標題、圖片 OCR 三個階段都走 LLM。預設使用 Google Gemini SDK，但可以在 `config.json` 或 `.env` 中切換成 Anthropic Claude 或 OpenAI ChatGPT。

| Provider  | `.env` API key 變數    | 預設 text model        | 預設 vision model      |
|-----------|------------------------|------------------------|------------------------|
| Gemini    | `GEMINI_API_KEY`       | `gemini-2.5-flash`     | `gemini-2.5-flash`     |
| Anthropic | `ANTHROPIC_API_KEY`    | `claude-sonnet-4-6`    | `claude-sonnet-4-6`    |
| OpenAI    | `OPENAI_API_KEY`       | `gpt-4o-mini`          | `gpt-4o`               |

切換方式（擇一）：

- `.env`: `LLM_PROVIDER=anthropic`
- `config.json` 加入：

  ```json
  "llm": { "provider": "anthropic" }
  ```

只需要在 `.env` 中填入你選用的那一個 provider 的 API key，其餘空白即可。每個階段的 model 也可以單獨覆蓋（`THREADS_LLM_CLASSIFIER_MODEL` / `THREADS_LLM_TITLE_MODEL` / `THREADS_LLM_OCR_MODEL` 環境變數，或 `config.json` 的 `llm.text-model` / `title-model` / `vision-model`）。

注意：目前 `scripts/image_ocr_to_markdown.py` 的 CLI 路徑只支援 `--ocr-backend gemini`；多 provider 走的是主要 pipeline（`scripts/import_bookmarks_to_markdown.py` + workflow）。

---

## 存回應時的上文與回覆

收藏的若是一則回應（而非原帖），classify 階段會匿名開啟該貼文的 permalink，從頁面內嵌資料抽出：

- **上文脈絡**：從母帖到你收藏那則回應的完整單線，寫進筆記的 `## 上文脈絡` 區（blockquote 縮排，逐則標注 `@作者`）。
- **回覆區**：原帖作者的回覆（連同被回覆的留言成對呈現）與長度達門檻的留言，寫進 Obsidian 可摺疊 callout（`> [!quote]- 回覆（N 則…）`），預設收合。
- frontmatter 增加 `saved_kind: root|reply`，標記收藏的是原帖還是回應。

上文會一併餵給分類與標題生成（回覆不會），提升存回應時的分類準確度；不增加額外網路請求與 LLM quota。

---

## 設定

`config.json`：

| Key | Default | 用途 |
| --- | --- | --- |
| `paths.catch-json` | `data/catch.json` | userscript 寫入、classify 讀取 |
| `paths.unsave-json` | `data/unsave.json` | classify 寫出、userscript 讀取 |
| `paths.markdown-output-root` | `output` | markdown 筆記輸出 root |
| `categories` | example list | Gemini classifier 可輸出的分類 |
| `unsaved-categories` | example subset | 這些分類會輸出到 `unsave.json` |
| `category-overrides` | `[]` | keyword / regex 強制分類規則 |
| `hints` | example rules | 注入 Gemini prompt 的判斷補充 |
| `image-ocr.backend` | `gemini` | lite 版本只支援 Gemini |
| `image-ocr.trigger-categories` | `["AI"]` | 哪些分類要做圖片 OCR |
| `thread-context.enabled` | `true` | 上文／回覆擷取開關；`false` 時行為與舊版相同 |
| `thread-context.min-reply-chars` | `12` | 留言至少幾個字才收進回覆區（原帖作者的回覆不受限） |
| `thread-context.max-replies` | `30` | 回覆區最多收錄幾串（超過截斷並在 callout 標題註記） |

路徑可以用相對路徑或本機絕對路徑。Windows 絕對路徑在 JSON 內必須用 forward slash（`C:/Users/<you>/...`）或將每個反斜線改成 `\\`（`C:\\Users\\<you>\\...`）。單一 `\` 在 JSON 是 escape 字元，`"D:\shane\..."` 會觸發 `json.decoder.JSONDecodeError: Invalid \escape`。

`.env`：

| Key | Default | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | required | classifier + 圖片 OCR |
| `CLASSIFIER_MODEL` | `gemini-2.5-flash` | Gemini classifier model |
| `IMAGE_OCR_ENABLED` | `true` | OCR step toggle |
| `IMAGE_OCR_MODEL` | `gemini-2.5-flash` | Gemini OCR model |
| `THREADS_CONTEXT_ENABLED` | `true` | 覆蓋 `thread-context.enabled` |
| `THREADS_CONTEXT_MIN_REPLY_CHARS` | `12` | 覆蓋 `thread-context.min-reply-chars` |
| `THREADS_CONTEXT_MAX_REPLIES` | `30` | 覆蓋 `thread-context.max-replies` |

pipeline 會在輸出目錄寫 `threads_events.jsonl` 事件紀錄；上文／回覆擷取結果對應 `reply_fetch_fetched_structured`（結構化解析成功）與 `reply_fetch_fetched_fallback`（退回純文字解析）事件。

---

## 已知限制

- auto-unsave 需要瀏覽器停在 `/saved`。
- File System Access 授權視為每次日常使用前的準備步驟；若 browser 顯示 handle 未綁定，請重新選檔。
- OCR 會用 Playwright render Threads post；若缺 browser binary，執行 `playwright install chromium`。
- Gemini quota：每次 scrape 會對每篇貼文分類一次，接著為 markdown title generation 再呼叫 Gemini；圖片 OCR 也會消耗同一支 Gemini key 的 quota。
- 回覆區只收「匿名可見」的回覆：深層回覆與登入後才看得到的內容不會收錄。
- Threads 改版可能使內嵌資料解析失效；此時自動退回舊的純文字解析（該篇筆記暫時沒有上文與回覆區，主文不受影響），`saved_kind` 會以 best-effort 標為 `root`。

---

## Troubleshooting

| 現象 | 可能原因 | 處理方式 |
| --- | --- | --- |
| 雙擊 `run_classify.cmd`／`run_classify.command` 顯示 `.venv not found` | 還沒建 venv | 跑「安裝 → Python 端」一次（依作業系統選 Windows／macOS） |
| classify 顯示 `json.decoder.JSONDecodeError: Invalid \escape` | `config.json` 的 Windows 路徑用了單一 `\` | 改成 `/`（`D:/foo/bar`）或 `\\`（`D:\\foo\\bar`） |
| classify 顯示 `GEMINI_API_KEY missing` | `.env` 沒填或 venv 沒拿到 | 確認 `.env` 有 `GEMINI_API_KEY=...`，重新雙擊 |
| panel 沒載入 AI classification | handle 未綁定或 autoLoad 關閉 | 重新綁定 `unsave.json`，勾選自動載入 |
| `unsave.json` 已更新但瀏覽器沒反應 | Auto AI Sync poll 還沒輪到 | 點 **立即檢查** 強制 poll |
| 取消儲存按鈕沒動作 | 不在 `/saved` 頁 | 把 tab 切回 `https://www.threads.com/saved` |

---

## 想要更自動化？

切到 `full` 分支可以額外得到：

- `watch_pipeline.py`：自動偵測 `catch.json` 變更觸發 classify。
- `agent_driver.py`：透過 `superpowers-chrome` + Chrome `--remote-debugging-port=9222` 從 terminal 直接觸發 panel scrape。
- Terminal B 確認 gate：每次 unsave 前 console 列出候選並要求 `y/n`。
- Chandra / vLLM 圖片 OCR backend。

代價：需要 Node.js、Claude Code + `superpowers-chrome` plugin、Chrome debug profile 設定、額外的 hook 檢查。
