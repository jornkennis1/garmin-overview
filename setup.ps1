# One-time setup on Windows. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Safe to run again: steps that are already done are skipped or asked about.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Ask([string]$Question) {
    $answer = Read-Host "$Question [Y/n]"
    return ($answer -eq "" -or $answer -match "^[yYjJ]")
}
function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

# ---------------------------------------------------------------- Python 3.12+
Step "Checking Python"
$python = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    $exe = $candidate[0]
    $pyArgs = @($candidate | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try { $version = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" } catch { continue }
    if ($LASTEXITCODE -eq 0 -and $version -and [version]"$version" -ge [version]"3.12") {
        $python = $candidate
        Write-Host "Found Python $version"
        break
    }
}
if (-not $python) {
    Write-Host "Python 3.12 or newer is required. Install it from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "(tick 'Add python.exe to PATH'), open a new terminal and run this script again." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- virtual environment
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Step "Installing packages into .venv"
if (-not (Test-Path $venvPython)) {
    $exe = $python[0]
    $pyArgs = @($python | Select-Object -Skip 1)
    & $exe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed (see above)." }
Write-Host "Packages installed."

# ---------------------------------------------------------------- personal settings
Step "Personal settings"
if (-not (Test-Path "settings.toml")) {
    Copy-Item "settings.example.toml" "settings.toml"
    Write-Host "Created settings.toml (HRmax, resting HR, tagging keywords, ...). Everything is optional;"
    Write-Host "the defaults work. Edit it any time with: notepad settings.toml"
} else {
    Write-Host "settings.toml already exists, leaving it alone."
}

# ---------------------------------------------------------------- Garmin login
Step "Garmin login"
Write-Host "You'll be asked for your Garmin email and password (unless you filled in .env)."
Write-Host "The password is only sent to Garmin; just the login tokens are kept, in ~\.garminconnect."
Write-Host "If you use two-step verification, Garmin sends you a code to type in."
& $venvPython -m garmin_sync.auth
if ($LASTEXITCODE -ne 0) {
    Write-Host "Login failed. Fix the problem above and run this script again." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- first sync
Step "First sync"
if (Ask "Fetch the last 30 days now (a few minutes)?") {
    $since = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
    & $venvPython -m garmin_sync.sync --since $since
    Write-Host "Later, run '.venv\Scripts\python -m garmin_sync.sync' to fetch your full history (can take hours;"
    Write-Host "stop with Ctrl+C any time, the next run resumes)."
}

# ---------------------------------------------------------------- Claude Desktop
Step "Claude Desktop (optional)"
if (Ask "Connect your training data to the Claude Desktop app (read-only)?") {
    & $venvPython claude_desktop_setup.py --install
}

# ---------------------------------------------------------------- 'garmin' terminal command
Step "'garmin' terminal command (optional)"
$line = "function garmin { param([string]`$Action) `$p = `"$PSScriptRoot`"; if (`$Action -eq `"sync`") { & `"`$p\sync_and_open.ps1`" } else { & `"`$p\start_dashboard.bat`" } }"
$hasProfile = Test-Path $PROFILE
if ($hasProfile -and (Select-String -Path $PROFILE -Pattern "function garmin" -Quiet)) {
    Write-Host "Your PowerShell profile already has a 'garmin' command."
} elseif (Ask "Add a 'garmin' command (open dashboard) and 'garmin sync' to your PowerShell profile?`n(this also allows local scripts: execution policy RemoteSigned for your user)") {
    if (-not $hasProfile) { New-Item -ItemType File -Path $PROFILE -Force | Out-Null }
    Add-Content -Path $PROFILE -Value "`n$line" -Encoding utf8
    if ((Get-ExecutionPolicy -Scope CurrentUser) -in @("Undefined", "Restricted")) {
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
    }
    Write-Host "Added. Open a new terminal to use it."
}

Step "Done"
Write-Host "Open the dashboard: double-click start_dashboard.bat, or run 'garmin' in a new terminal."
