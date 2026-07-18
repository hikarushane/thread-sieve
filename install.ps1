# ThreadSieve 一行安裝 bootstrap（Windows）
# 用法：irm https://raw.githubusercontent.com/hikarushane/thread-sieve/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/hikarushane/thread-sieve.git"
$TargetDir = if ($env:THREADSIEVE_DIR) { $env:THREADSIEVE_DIR } else { "thread-sieve" }
$PythonVersion = "3.12"

function Step($n, $msg) { Write-Host "`n[$n] $msg" }
function Fail($msg) {
    Write-Host "`n安裝失敗：$msg" -ForegroundColor Red
    throw "ThreadSieve install aborted"
}

Step "1/6" "檢查 git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "找不到 git。請先安裝 https://git-scm.com/download/win ，重開 PowerShell 後再跑一次"
}

Step "2/6" "檢查 uv（Python 環境管理工具）"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "未安裝，執行 uv 官方安裝器…"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fail "uv 裝好了但這個視窗還找不到，請重開 PowerShell 再跑一次本指令"
    }
}

Step "3/6" "下載 ThreadSieve → $TargetDir\"
if (Test-Path $TargetDir) {
    Fail "目錄 $TargetDir 已存在。已裝過的話直接雙擊 run_classify.cmd；要重裝請先改名或移除該目錄"
}
git clone $RepoUrl $TargetDir
Set-Location $TargetDir

Step "4/6" "建立 Python $PythonVersion 虛擬環境（系統 Python 版本不對也沒關係，uv 會自動下載，不動你原本的環境）"
uv venv .venv --python $PythonVersion

Step "5/6" "安裝依賴與 Chromium（第一次會下載瀏覽器，需要幾分鐘）"
uv pip install -r requirements.txt --python .venv\Scripts\python.exe
& .venv\Scripts\python.exe -m playwright install chromium

Step "6/6" "產生設定檔"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path config.json)) { Copy-Item config.json.example config.json }

Write-Host @"

✅ 安裝完成。專案位置：$(Get-Location)

下一步：
  1. 編輯 .env         → 填入 GEMINI_API_KEY
  2. 編輯 config.json  → 分類清單與輸出路徑（見 README「安裝 → 設定」）
  3. 瀏覽器端一次性設定（Tampermonkey userscript）→ 見 README「安裝 → Browser 端」

之後每次使用：雙擊 run_classify.cmd
"@
