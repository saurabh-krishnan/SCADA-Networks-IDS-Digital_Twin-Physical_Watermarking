# One-command startup for the SCADA Digital-Twin Security Platform (Windows PowerShell).
# Builds the frontend (if needed), then serves API + UI from a single Uvicorn process.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
  py -3 -m venv (Join-Path $root "backend\.venv")
  & $py -m pip install --upgrade pip
  & $py -m pip install -r (Join-Path $root "backend\requirements.txt")
}

if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
  Write-Host "Building frontend..." -ForegroundColor Cyan
  Push-Location (Join-Path $root "frontend")
  if (-not (Test-Path "node_modules")) { npm install }
  npm run build
  Pop-Location
}

Write-Host "`nStarting SCADA platform on http://127.0.0.1:8000  (Ctrl+C to stop)`n" -ForegroundColor Green
Push-Location (Join-Path $root "backend")
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location
