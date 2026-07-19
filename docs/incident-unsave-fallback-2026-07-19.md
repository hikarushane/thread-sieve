# 事故紀錄：unsave 低報 ＋ 關鍵詞 fallback 誤殺（2026-07-19）

## 症狀

使用者以新產出的 `data/unsave.json`（53 篇待取消）連跑三次「取消儲存」：

- 第一次：面板報「5 已驗證」
- 第二次：面板報「6 已驗證 / 0 待刷新 / 0 失敗」，紅字「仍有 54 篇未執行」
- 第三次（開 debug log）：「10 已驗證 / 0 待刷新 / 0 失敗」，`stopReason: bottom_stalled`

表面看像「53 篇只成功一小部分」。

## 根因（兩個獨立問題）

### A. 低報——53 篇其實第一輪就取消成功了

debug log（`data/threads-unsave-debug.ndjson`，389 events）證據：

- 351 個 `ai_sync_snapshot`、80 個 unique DOM key，與 unsave.json 53 個目標 key **交集 = 0**（`reconciledMissingCount: 54`）。
- 畫面上出現 24 篇 catch.json 的「保留」組貼文（29 篇中的 83%、ID 完全相同），**0 篇「取消」組**——若 53 篇仍在收藏，機率上不可能。
- 人工抽查 unsave.json 前三筆貼文 URL：**全部已是未儲存狀態**。

結論：第一輪執行時大部分取消點擊已在伺服器端生效，但面板 verified 計數只認「畫面即時消失」的案例（Threads 虛擬捲動與延遲刷新導致大量低報），使用者誤以為失敗而重複執行。

### B. 關鍵詞 fallback 誤殺——取消了 10 篇不在任何清單上的貼文

第三輪「10 已驗證」的 10 篇 key **全部不在 unsave.json、也不在 catch.json**，post ID 排序比整份 catch 範圍更舊（7/02 之前的舊收藏）：

```
DaCIGiSlMBY DZ_JxSCD3Xw DaAHoQLk8CT DaAMkKiiA0W DZ_A-HKES_z
DZ8njT_AUgT DZ87-APjolu DZ5Oh4PCVzw DZ7jG_7Dw1E DZ3pUgmiVeV
```

機制：`getAiItemForPost()` 查不到分類時退到 `getLocalAiCandidate()`（本地關鍵詞：AI／prompt／自動化／工作流／知識庫等，confidence 0.56），`addHighlightedEntriesToSelection()` 在開跑時與每輪捲動把這些 fallback 候選**自動加進取消選取**——分類器沒審過的貼文就這樣被取消儲存。第一、二輪的 5＋6 篇極可能也是同類誤殺（未開 debug log，key 無法找回）。

## 修復（v0.4.2）

1. **fallback 只標亮、永不自動選取**：`addHighlightedEntriesToSelection()` 遇 `aiItem.localCandidate` 直接跳過；手動勾選 checkbox 的路徑保留。
2. **完成訊息區分兩種「未執行」**：`reconciledMissingKeys`（整輪掃完仍未在頁面出現）報為「可能已在先前執行取消（請重新整理頁面確認）」，與「尚未捲到／按鈕未辨識」分開，避免再追鬼。

## 判讀 debug log 的方法（下次直接用）

面板「debug log」鈕授權 NDJSON 檔後重跑，關鍵 event：

| event | 回答什麼 |
|---|---|
| `unsave_run_started` | 開跑時選取數、畫面上可見選取數 |
| `ai_sync_snapshot.visibleSignature` | 每輪 DOM 實際出現的 key（驗證目標貼文有沒有真的在頁面上） |
| `ai_sync_snapshot.unmatchedEntries` | 畫面上比對不到分類的貼文（含內文前 120 字，可反查 catch.json） |
| `unsave_item_result` | 實際被點擊取消的 key 與結果 |
| `unsave_run_finished.stopReason` | 迴圈為何停：`bottom_stalled` / `scroll_stalled` / `no_progress` / `ai_order_boundary_no_selected` |
| `unsave_missing_keys_reconciled` | 選取了但整輪沒在頁面出現的 key（＝多半已取消） |

## 教訓

- 「已驗證」數字≠實際取消數：Threads 頁面延遲刷新會系統性低報。重跑前先重新整理 /saved 並目視確認。
- 自動化刪除類操作（取消儲存）**只能作用於明確清單**；任何啟發式 fallback 只准提示、不准行動。
- post ID（base64url）大致單調遞增，可用排序粗判貼文新舊——本次靠這點確認誤殺的 10 篇全是舊收藏。
