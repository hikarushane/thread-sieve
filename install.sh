#!/usr/bin/env bash
# ThreadSieve 一行安裝 bootstrap（macOS）
# 用法：curl -fsSL https://raw.githubusercontent.com/hikaru-yeh/thread-sieve/main/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/hikaru-yeh/thread-sieve.git"
TARGET_DIR="${THREADSIEVE_DIR:-thread-sieve}"
PYTHON_VERSION="3.12"

step() { printf '\n[%s] %s\n' "$1" "$2"; }
fail() { printf '\n安裝失敗：%s\n' "$1" >&2; exit 1; }

step 1/6 "檢查 git"
command -v git >/dev/null 2>&1 || fail "找不到 git。執行 xcode-select --install 安裝後再跑一次"

step 2/6 "檢查 uv（Python 環境管理工具）"
if ! command -v uv >/dev/null 2>&1; then
  echo "未安裝，執行 uv 官方安裝器…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv 裝好了但這個 shell 還找不到，請重開 Terminal 再跑一次本指令"
fi

step 3/6 "下載 ThreadSieve → ${TARGET_DIR}/"
[ -e "$TARGET_DIR" ] && fail "目錄 ${TARGET_DIR} 已存在。已裝過的話直接雙擊 run_classify.command；要重裝請先改名或移除該目錄"
git clone "$REPO_URL" "$TARGET_DIR"
cd "$TARGET_DIR"

step 4/6 "建立 Python ${PYTHON_VERSION} 虛擬環境（系統 Python 版本不對也沒關係，uv 會自動下載，不動你原本的環境）"
uv venv .venv --python "$PYTHON_VERSION"

step 5/6 "安裝依賴與 Chromium（第一次會下載瀏覽器，需要幾分鐘）"
uv pip install -r requirements.txt --python .venv/bin/python
.venv/bin/python -m playwright install chromium

step 6/6 "產生設定檔"
[ -f .env ] || cp .env.example .env
[ -f config.json ] || cp config.json.example config.json

cat <<DONE

✅ 安裝完成。專案位置：$(pwd)

下一步：
  1. 編輯 .env         → 填入 GEMINI_API_KEY
  2. 編輯 config.json  → 分類清單與輸出路徑（見 README「安裝 → 設定」）
  3. 瀏覽器端一次性設定（Tampermonkey userscript）→ 見 README「安裝 → Browser 端」

之後每次使用：雙擊 run_classify.command
DONE
