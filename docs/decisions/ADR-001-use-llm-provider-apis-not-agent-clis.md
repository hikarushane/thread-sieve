# ADR-001: LLM backend 走 provider API，不走本機 agent CLI

## Status

Accepted

## Date

2026-07-18

## Context

ThreadSieve 的核心情境是**批量處理**：使用者累積數十到上百篇 Threads 收藏後，雙擊 `run_classify.cmd`／`run_classify.command` 一次跑完。pipeline 逐篇序列執行，每篇至少 2 個 LLM call（分類＋標題），OCR 觸發類別每張圖再加 1 個 vision call——一批 82 篇 ≈ 164+ 個 call。

約束條件：

- 無人值守執行（雙擊 launcher，跑完才回來看），中途不能有互動或登入提示。
- 分類結果要可重現（同一篇重跑不應換類別），並嚴格輸出「只有類別名」。
- 一般使用者環境：只需要填一把 API key 就能動，不預設安裝了哪些開發工具。

2026-06-08 multi-provider 重構時，CLI-subprocess backend 已被列為 out of scope，但當時未記錄理由。2026-07-18 曾實作 `claude-code`（`claude -p`）與 `codex`（`codex exec`）兩個 CLI backend 並於同日移除（git history：`ae22d4a`〜`c6e2bbf` 加入、`359e3d6` 移除），本 ADR 補記完整決策。

## Decision

LLM backend 僅支援 provider API（`gemini`｜`anthropic`｜`openai`），透過 `LLMClient` Protocol＋`llm_factory` 分派。不支援、也不再加回本機 agent CLI backend。

## Alternatives Considered

### Claude Code CLI backend（`claude -p`，2026-07-18 實作後移除）

- Pros：免 API key（用 CLI 既有登入）、免額外 SDK；對已訂閱 Claude 的使用者零邊際成本感。
- Cons（實測）：
  - 每次呼叫 spawn 整個 Node app＋agent session 初始化：trivial call 實測 **5.6s vs Gemini API 1.5s**；82 篇批次估 15 分鐘起跳 vs API 約 4 分鐘，真實 prompt 更長差距更大。
  - 消耗 Claude 訂閱的 5 小時 window quota——與使用者的 coding 工作共用同一額度。
  - 無法設 `temperature=0`，分類不可重現。
  - agent session 輸出可能夾雜非答案文字，「只回類別名」的輸出紀律較差。
  - 依賴 CLI 登入狀態與版本 flags：實作當日即踩到 `--bare` 導致「Not logged in」exit 1；CLI 改版即壞。
- Rejected：批量、無人值守、要求可重現的 pipeline 與 agent CLI 的設計目標（互動式、單次、agentic）根本不合。

### OpenAI Codex CLI backend（`codex exec`，2026-07-18 實作後移除）

- Pros／Cons：與 Claude Code CLI 同構——每 call 進程啟動開銷、吃 ChatGPT 訂閱 quota、無 temperature 控制；另需 `--sandbox read-only`＋`--output-last-message` 等 flags 繞過 agent 行為。
- Rejected：同上。

### 混合模式（批量走 API、零星走 CLI）

- Pros：理論上兼得兩者。
- Cons：pipeline 全程共用單一 client（分類＋標題＋OCR），per-stage 分流要改架構；「零星幾篇」用 API 的成本本來就趨近於零，CLI 省下的 key 設定換來兩套路徑的維護。
- Rejected：複雜度不換來實際價值。

## Consequences

- 使用者必須申請至少一把 API key（預設 gemini，`gemini-2.5-flash` 有免費額度，門檻低）。
- 三個 API adapter 均設 `temperature=0`，分類可重現；SDK 例外語意清楚，retry 邏輯簡單。
- 批次耗時可預估（~1.5s/call），不佔用任何訂閱 quota。
- 未來若要加後端，加「API 型」provider（新 adapter 實作 `LLMClient` Protocol 即可）；agent CLI 類提案應先讀本 ADR，除非批量特性或 CLI 的批次介面有根本改變，否則不再重議。
