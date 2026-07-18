$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot
python scripts/watch_pipeline.py
