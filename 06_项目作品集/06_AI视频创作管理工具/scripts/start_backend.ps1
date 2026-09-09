# Start API with a graceful-shutdown timeout so --reload cannot hang forever.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "src"
python -m uvicorn ai_video_manager.api.app:create_app `
  --factory `
  --host 127.0.0.1 `
  --port 8000 `
  --reload `
  --timeout-graceful-shutdown 5
