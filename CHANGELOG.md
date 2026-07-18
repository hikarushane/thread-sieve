# Changelog

## 2026-07-18 — 新增 claude-code 與 codex CLI 分類 backend

### 新功能

- **`llm.provider` 新選項 `claude-code` 與 `codex`**：分類／標題／圖片 OCR 可改走本機已登入的 Claude Code CLI（`claude -p`）或 OpenAI Codex CLI（`codex exec`），不需 API key。
  - model 欄位留空＝使用 CLI 自己設定的預設模型；仍可用 `text-model` 等欄位或 `THREADS_LLM_*` env 指定。
  - 兩者皆在隔離的暫存目錄執行（擋掉專案 CLAUDE.md／專案 hooks）；codex 另以 `--sandbox read-only` 執行，不會碰使用者專案。
- `.env.example` 與 `config.json.example` 補上五種 provider（gemini｜anthropic｜openai｜claude-code｜codex）的填寫範例與說明。

## 2026-07-18 — macOS launcher 與跨平台安裝說明

### 新功能

- **`run_classify.command`**：macOS 版雙擊啟動器，對應既有的 Windows `run_classify.cmd`。activate `.venv` 後執行 `scripts/import_bookmarks_to_markdown.py`，結束顯示 `[DONE]`／`[FAILED]`。

### 文件

- README（中英）「安裝 → Python 端」拆成 **Windows（PowerShell）** 與 **macOS（Terminal）** 兩塊；SOP 步驟 3、指令列備案、桌面捷徑、Troubleshooting、流程圖同步兩平台。

## 2026-07-14 — 存回應時擷取單線上文與回覆區

突破先前已知限制：「存的是某個回應就看不到上文」「看不到原始帖作者的回覆」。

### 新功能

- **上文脈絡**：收藏的是回應時，筆記新增 `## 上文脈絡` 區，呈現母帖到該回應的完整單線（巢狀 blockquote，逐則標注 `@作者`，多層巢狀回覆亦完整）。
- **回覆區**：新增 Obsidian 可摺疊 callout（`> [!quote]- 回覆（N 則，含原作者 M 則）`，預設收合）：
  - 原帖作者的回覆全數保留，並與被回覆的留言成對縮排呈現；
  - 其他留言過濾純 emoji／過短內容（門檻可調）；
  - 超過上限截斷並在標題註記。
- **frontmatter 新欄位 `saved_kind`**：`root`（原帖）或 `reply`（回應）。
- **分類準度提升**：上文脈絡（不含回覆區）一併餵給 LLM 分類與標題生成，解決存回應時因缺上下文而誤分類的問題。
- **新 config 區塊 `thread-context`**（`config.json`，env `THREADS_CONTEXT_*` 優先）：
  - `enabled`（預設 `true`；`false` 時行為與舊版相同）
  - `min-reply-chars`（預設 `12`）
  - `max-replies`（預設 `30`）

### 實作說明

- 資料來源為貼文 permalink 頁面的內嵌結構化資料，在既有的單次 Playwright 匿名訪問中順帶解析——userscript 零改動、零額外網路請求、零額外 LLM quota。
- Threads 改版導致解析失效時，自動退回舊版純文字解析；單篇失敗不中斷整批。
- 事件紀錄（`threads_events.jsonl`）新增 `reply_fetch_fetched_structured` 與 `reply_fetch_fetched_fallback` 事件。

### 已知限制

- 回覆區只收「匿名可見」的回覆；深層回覆與登入牆之後的內容不收錄。
- 走純文字 fallback 時 `saved_kind` 以 best-effort 標為 `root`。
