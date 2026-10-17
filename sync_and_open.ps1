# Daily helper: sync new Garmin data, then open the dashboard.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File C:\path\to\garmin_overview\sync_and_open.ps1
# Add -NoSync to only open the dashboard.
param([switch]$NoSync)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Virtual environment not found. Follow the one-time setup in README.md first." -ForegroundColor Red
    exit 1
}

if (-not $NoSync) {
    Write-Host "Syncing Garmin data ..." -ForegroundColor Cyan
    & $python -m garmin_sync.sync
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Sync failed (see above). Opening the dashboard with the data you already have." -ForegroundColor Yellow
    }
}

Write-Host "Opening dashboard at http://localhost:8501 (press Ctrl+C here to stop it) ..." -ForegroundColor Cyan
& $python -m streamlit run app/Overview.py
