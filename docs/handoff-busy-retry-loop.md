# Handoff：查 classify busy retry loop（下一 session 用）

> 用法：整段貼給新 session，或點 Claude Code 的待辦 chip「Investigate classify busy retry loop」。

---

## 1. 目標

查明 `scripts/import_bookmarks_to_markdown.py`（實作在 `note_generator/`）為何出現 CPU 空轉的 busy loop，且 Ctrl+C 無法中斷。只查原因＋提修法，**未經使用者同意不改 code、不重跑真實 classify**。

## 2. 當前狀態／觀測證據（2026-07-18 22:54 前後，macOS）

- 三個 classify 同時在跑（22:50、22:54、22:56 各起一個），讀同一份 `data/catch.json`（82 篇）、同一份 `config.json`（Gemini backend，`gemini-2.5-flash`）。
- 22:54 那個（PID 41290，終端機前景）：`ps` 顯示 **R+、98.5% CPU、累積 CPU 時間 6:28**（wall ~9 分鐘）——正常流程應在等 Gemini API 回應、CPU 近 0。
- 同時刻另外兩個 run CPU 時間僅 0:02，狀態 S（正常等待）。只有中間那個空轉。
- **Ctrl+C 對它無效**（使用者按了沒反應），最後用 `kill -TERM` 才停。
- 三個 run 都沒跑到寫 `data/unsave.json`（該檔仍是 2026-07-18T17:07 UTC 舊版）。
- stdout 無任何輸出（可能只是 buffering，不一定是線索）。

## 3. 已變更檔案

無。本次事故未改任何 code；`data/unsave.json` 維持舊版，不可覆蓋。

## 4. 決策紀錄

- 使用者裁決：**先不查、先不重跑**（2026-07-19）；本 handoff 就是下一棒的起點。
- 三個併發 run 是使用者自己重複啟動＋agent 背景各一，非 bug 本體；但併發可能是觸發條件（如 Gemini 429 rate limit）。

## 5. 失敗事項（下一棒勿重踩）

- Ctrl+C 中斷失敗——查時注意是否有 `except` 吞掉 `KeyboardInterrupt`（如 `except BaseException` 或裸 `except:`）。
- 勿用「重跑一次真 classify」當復現手段：燒 Gemini 額度且 82 篇要數分鐘。復現請 mock client 或假 API key。

## 6. 精確下一步

1. 讀 `note_generator/infrastructure/gemini_client.py` 全文，找 retry／loop：`grep -n "while\|for \|retry\|sleep\|except" note_generator/infrastructure/gemini_client.py`。
2. 同樣檢查 `note_generator/services/llm_client.py`、`category_classifier.py`、`title_generator.py`、`image_ocr_enricher.py`、`threads_reply_enricher.py`、`workflows/import_bookmarks_to_markdown.py`。
3. 判準（驗收條件，逐項可打勾）：
   - [ ] 指出空轉迴圈確切位置（檔案:行號），或排除 note_generator 內有 busy loop 並給替代解釋（附證據）。
   - [ ] 解釋為何 98.5% CPU（retry 無 sleep/backoff？無限迴圈？spin wait？）。
   - [ ] 解釋為何 Ctrl+C 無效（吞 KeyboardInterrupt？signal 被 SDK 攔？）。
   - [ ] 評估「三併發 → 429 → 無退避重試」假說：成立或否，附程式碼證據。
   - [ ] 提出最小修法（上限次數＋exponential backoff＋不吞 KeyboardInterrupt），**只提案，不動手**。
4. 回報格式：≤100 行，結論先行，全部引用 `檔案:行號`，不貼大段原文。

## 7. 制度欄位

- 接手 model：**opus 級或更強**（診斷模糊題，C §3）。
- 額度餘量：未確認。
- 禁區：`data/*.json`（不可覆蓋）、`README.md`／`README.en.md`（consistency gate，未經同意不改）、不得真跑 Gemini API。
