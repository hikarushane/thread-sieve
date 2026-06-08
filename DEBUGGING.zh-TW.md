# 修 Bug 流程操作手冊（繁體中文）

英文版參考：[`DEBUGGING.md`](DEBUGGING.md)。

## 這是什麼

`/debug-loop` 是專案內建的 Claude Code slash command，把 Superpowers 的三個 skill 串起來，逼 Claude 用紀律修 bug，避免亂猜亂改、亂宣稱「修好了」。

串接順序：

1. **systematic-debugging** — 先找 root cause，不准沒查清楚就改 code
2. **test-driven-development** — 先寫一個會 fail 的 regression test，再動產品程式碼
3. **verification-before-completion** — 沒有 fresh command output 為憑，就不准說修好

同一個 bug 連修 3 次都失敗 → Claude 會自動停下來，請你決定要不要從架構層面重新思考，而不是繼續疊補丁。

## 使用前準備（每次都要確認）

1. Chrome 用 `--remote-debugging-port=9222` 啟動（見 README 第 0.C 節）
2. `https://www.threads.com/saved` 分頁有開著
3. Tampermonkey 儀表板 → 點進 **ThreadSieve (Auto)** 進編輯器（這個 editor 分頁必須一直開著，helper 會用標題自動找）
4. venv 啟動：`.\.venv\Scripts\Activate.ps1`
5. `.env` 已設好，且 `config.json` 裡 `paths.chrome-ws-cli` 已設好

任何一項沒做到，helper 會回報錯誤，loop 不會繼續往下跑。

## 怎麼用（標準流程）

在 Claude Code 任何 session 打：

```
/debug-loop watcher 在 catch.json 500ms 內連續更新時會漏掉一次
```

Claude 接下來會自動：

1. 重現 bug、看完整錯誤訊息
2. 提出**一個**假設、最小幅度驗證
3. 寫一個會 fail 的 regression test → 跑 pytest 確認 RED
4. 做最小修改 → 跑 pytest 確認 GREEN → 再跑完整 test suite
5. 如果改到 userscript，自動執行：
   ```
   python scripts/push_userscript.py --probe
   ```
   把 JS 推進 Tampermonkey、點 Save、reload `/saved`、再跑 `agent_driver.py probe` 確認 panel 還活著
6. 用 fresh 的指令輸出當證據，才會宣稱修好

中途某次修改失敗，Claude 不會疊新補丁。會回到第 2 步：讀新的錯誤、重新形成假設、再試一次。

連續三次失敗 → 停下來問你。

## JS-only bug 的誠實邊界

`tests/` 都是純 Python，只能驗 file artifact（`data/catch.json`、`data/unsave.json`）或 Python 模組。**完全活在 userscript 裡的 bug**（DOM 抓取、Tampermonkey GM API、FS Access handle、panel UI 行為）pytest 看不到。

這種情況 Claude 會誠實標註：

- regression「test」改用 `agent_driver.py probe` 做結構性檢查
- 加上一個你能自己跑的手動重現步驟
- 不會寫一個空洞的 pytest 假裝過綠燈

verification-before-completion gate 會要求把新的 probe 輸出 + 手動重現結果讀完，才結束 loop。

## 手動指令（loop 中途想自己跑）

| 指令 | 用途 |
| --- | --- |
| `python scripts/push_userscript.py` | 把目前 `userscripts/threads-scriber-auto.user.js` 推進 Tampermonkey、Save、reload `/saved` |
| `python scripts/push_userscript.py --probe` | 同上，再跑 `agent_driver.py probe`（**每次改 userscript 都建議用這個**） |
| `python scripts/push_userscript.py --no-reload` | 只推 + 存檔，不 reload `/saved` |
| `python scripts/agent_driver.py probe` | 唯讀檢查：panel 存在、`SCRIPT_VERSION` 對得上、FS Access handle 有 bound |
| `pytest tests/` | 跑完整 Python 測試 |

## 常見錯誤對應

| 出錯訊號 | 原因 | 怎麼修 |
| --- | --- | --- |
| `push_userscript.py` exit 2「no Tampermonkey editor tab」 | 編輯器分頁沒開 | 開 Tampermonkey dashboard，點進「ThreadSieve (Auto)」 |
| `push_userscript.py` exit 2「chrome-ws CLI path missing」 | `config.json` 路徑沒設或被清空 | 補回 `paths.chrome-ws-cli`（見 README 第 0.B 節） |
| `push_userscript.py` exit 3「save failed」 | Tampermonkey 改版，Save 按鈕 selector 變了 | 用 `chrome-ws eval <tab> "[...document.querySelectorAll('button[title]')].map(b=>b.outerHTML)"` 查目前的 selector，更新 `click_save()` 裡的 title regex / id pattern |
| `push_userscript.py` exit 4「reload /saved failed」 | `/saved` 分頁關了，或 chrome-ws 斷線 | 重新打開 `https://www.threads.com/saved`；確認 Chrome 在 9222 port |
| 推完後 `probe` 報 `panel missing` | userscript 有語法錯，Tampermonkey parse 失敗 | 打開 Tampermonkey 該腳本的 Console 看錯誤訊息，修完再推 |
| `probe` 報 `scriptVersion=... expected 0.3.2` | `SCRIPT_VERSION` constant 跟 `@version` header 對不上 | 在 `userscripts/threads-scriber-auto.user.js` 把兩處都 bump；或重跑 `scripts/_rebuild_userscript.py` |

## 甚麼時候不要用 `/debug-loop`

這個 loop 是針對 bug 設計的。下列情況用一般 TDD 流程就好，不需要 stop-after-3 那種紀律：

- 純文件修改（README、註解）
- 純 config 修改（`config.json`、`.env`）
- 新功能開發（用 TDD，但不需要 loop 的 stop conditions）

## 想知道更多

- Slash command 本體：[`.claude/commands/debug-loop.md`](.claude/commands/debug-loop.md)
- 推送 helper 原始碼：[`scripts/push_userscript.py`](scripts/push_userscript.py)
- 既有的 chrome-ws driver：[`scripts/agent_driver.py`](scripts/agent_driver.py)
- Superpowers 三個 skill 的完整定義在 `~/.claude/plugins/cache/claude-plugins-official/superpowers/<version>/skills/`
