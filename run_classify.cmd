@echo off
REM ThreadSieve - double-click launcher for path 1 (no typing).
REM Activates local venv and runs the classify + markdown + unsave.json step.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] .venv not found. Run setup first:
  echo   python -m venv .venv
  echo   .\.venv\Scripts\Activate.ps1
  echo   pip install -r requirements.txt
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python scripts\import_bookmarks_to_markdown.py
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 (
  echo [FAILED] exit code %EXITCODE%
) else (
  echo [DONE] classify finished.
)
pause
endlocal & exit /b %EXITCODE%
