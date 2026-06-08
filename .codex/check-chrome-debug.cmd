@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-chrome-debug.ps1"
exit /b %ERRORLEVEL%
