# ThreadSieve (lite)

[English](README.en.md)

> 一般使用者版本：免裝 superpowers-chrome、免開 watcher、免 Chrome debug port。  
> 完整自動化版本（terminal watcher + agent-driven scrape + Chandra OCR）請切到 `main` 分支。

Threads 收藏貼文的問題：

  ❌ 存了幾百篇
  ❌ 沒有分類
  ❌ 找不到
  ❌ 最後全部爛在那裡

ThreadSieve 是一套本機端自動化流程，把 Threads 收藏貼文篩選、分類，轉成 markdown 筆記，並自動取消儲存指定分類的貼文。

抓取後進入分類與筆記產生的貼文內容包含：主文內容、作者在同串貼文中的留言，以及貼文圖片經 OCR 轉出的文字。

兩層：

- `userscripts/threads-scriber-auto.user.js`：Tampermonkey userscript，抓 Threads saved 頁面寫出 `catch.json`。
- `scripts/*.py`：Python pipeline，分類、寫 markdown、Gemini 圖片 OCR。

---

## 流程概覽

```text
[Threads /saved (瀏覽器 panel scrape)] -> catch.json
                                            |
                                            v
                              雙擊 run_classify.cmd
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

不需要 Node.js，不需要 `--remote-debugging-port`，不需要任何 Claude Code plugin。

---

## 安裝

### 0. Clone 此 repo

```powershell
git clone -b lite https://github.com/hikaru-yeh/thread-sieve.git
cd thread-sieve
```

### 1. Python 端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
copy config.json.example config.json
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

## 日常 SOP（免打字）

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

雙擊專案根目錄的 `run_classify.cmd`。會跳出一個 console 視窗，自動 activate `.venv` 並執行 `scripts/import_bookmarks_to_markdown.py`，結束時顯示 `[DONE]` 或 `[FAILED]`，按任意鍵關閉。

若想做桌面捷徑：右鍵 `run_classify.cmd` → 傳送到 → 桌面（建立捷徑）。之後雙擊桌面捷徑即可。

這支 script 對每篇貼文分類一次，並用同一批分類結果寫出 markdown 筆記和 `unsave.json`。若分類結果符合 `config.json` → `image-ocr.trigger-categories`，圖片 OCR 也會自動執行。

備案：偏好用指令列：

```powershell
.\.venv\Scripts\Activate.ps1
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

路徑可以用相對路徑或本機絕對路徑。Windows JSON 路徑建議用 forward slash：`C:/Users/<you>/...`。

`.env`：

| Key | Default | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | required | classifier + 圖片 OCR |
| `CLASSIFIER_MODEL` | `gemini-2.5-flash` | Gemini classifier model |
| `IMAGE_OCR_ENABLED` | `true` | OCR step toggle |
| `IMAGE_OCR_MODEL` | `gemini-2.5-flash` | Gemini OCR model |

---

## 已知限制

- auto-unsave 需要瀏覽器停在 `/saved`。
- File System Access 授權視為每次日常使用前的準備步驟；若 browser 顯示 handle 未綁定，請重新選檔。
- OCR 會用 Playwright render Threads post；若缺 browser binary，執行 `playwright install chromium`。
- Gemini quota：每次 scrape 會對每篇貼文分類一次，接著為 markdown title generation 再呼叫 Gemini；圖片 OCR 也會消耗同一支 Gemini key 的 quota。

---

## Troubleshooting

| 現象 | 可能原因 | 處理方式 |
| --- | --- | --- |
| 雙擊 `run_classify.cmd` 顯示 `.venv not found` | 還沒建 venv | 跑「安裝 → Python 端」一次 |
| classify 顯示 `GEMINI_API_KEY missing` | `.env` 沒填或 venv 沒拿到 | 確認 `.env` 有 `GEMINI_API_KEY=...`，重新雙擊 |
| panel 沒載入 AI classification | handle 未綁定或 autoLoad 關閉 | 重新綁定 `unsave.json`，勾選自動載入 |
| `unsave.json` 已更新但瀏覽器沒反應 | Auto AI Sync poll 還沒輪到 | 點 **立即檢查** 強制 poll |
| 取消儲存按鈕沒動作 | 不在 `/saved` 頁 | 把 tab 切回 `https://www.threads.com/saved` |

---

## 想要更自動化？

切到 `main` 分支可以額外得到：

- `watch_pipeline.py`：自動偵測 `catch.json` 變更觸發 classify。
- `agent_driver.py`：透過 `superpowers-chrome` + Chrome `--remote-debugging-port=9222` 從 terminal 直接觸發 panel scrape。
- Terminal B 確認 gate：每次 unsave 前 console 列出候選並要求 `y/n`。
- Chandra / vLLM 圖片 OCR backend。

代價：需要 Node.js、Claude Code + `superpowers-chrome` plugin、Chrome debug profile 設定、額外的 hook 檢查。
