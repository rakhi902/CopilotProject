# One-click setup + launcher for local development (Windows / PowerShell).
#
# Zero setup: local development uses a SQLite file, so there's no database server
# to install. Safe to run any time; it skips whatever is already done:
#   1. find Python 3
#   2. create the virtualenv (backend\.venv) if missing
#   3. install the dependencies if they aren't installed yet
#   4. create backend\.env (with a generated JWT secret) if missing
#   5. run the database migrations (creates the local SQLite database)
#   6. start the API and the frontend, then open your browser
#
# Run it from the project root:  .\run.ps1
# (If PowerShell blocks the script, allow local scripts for your user once:
#    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1. Find a Python 3 to build the virtualenv with (prefer 3.10-3.12).
Step "Looking for Python 3"
$BootExe = $null
$BootArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.11", "-3.12", "-3.10")) {
        $null = & py $v -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $BootExe = "py"; $BootArgs = @($v); break }
    }
    if (-not $BootExe) { $BootExe = "py"; $BootArgs = @("-3") }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $BootExe = "python"
}
if (-not $BootExe) {
    Write-Host "Python 3 wasn't found. Install it from https://www.python.org/downloads/ (3.10-3.12) and re-run .\run.ps1." -ForegroundColor Red
    exit 1
}
Write-Host ("Using " + (& $BootExe @BootArgs --version))

# 2. Create the virtualenv if it isn't there.
if (-not (Test-Path $Py)) {
    Step "Creating the virtual environment (backend\.venv)"
    & $BootExe @BootArgs -m venv $Venv
}

# 3. Install dependencies only if they're missing from the venv.
Step "Checking dependencies"
$depCheck = "import fastapi, uvicorn, sqlalchemy, alembic, pydantic_settings, langgraph, langchain_groq, fpdf, docx, pypdf, jose, passlib, bs4"

#$null = & $Py -c $depCheck 2>$null
#if ($LASTEXITCODE -eq 0) {
#    Write-Host "Dependencies already installed."
#} else {
#    Write-Host "Installing dependencies (first run can take a minute)..."
#    & $Py -m pip install --upgrade pip
#    & $Py -m pip install -r (Join-Path $Backend "requirements.txt")
#}
try {
    & $Py -c $depCheck *> $null
    $depsInstalled = $true
}
catch {
    $depsInstalled = $false
}

if ($depsInstalled) {
    Write-Host "Dependencies already installed."
}
else {
    Write-Host "Installing dependencies (first run can take a minute)..."
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -r (Join-Path $Backend "requirements.txt")
}
# 4. Make sure backend\.env exists (for your JWT secret and Groq key).
Step "Preparing backend\.env"
& $Py (Join-Path $Backend "setup_env.py")
Write-Host "  (Add your GROQ_API_KEY to backend\.env for AI generation: https://console.groq.com/keys)" -ForegroundColor Yellow

# 5. Create / update the local SQLite database via the migrations.
Step "Running database migrations (SQLite)"
Push-Location $Backend
& $Py -m alembic upgrade head
Pop-Location

# 6. Start the servers (each in its own window) and open the browser.
Step "Starting the servers"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Backend'; & '$Py' -m uvicorn app.main:app --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Frontend'; & '$Py' -m http.server 5500"

Write-Host "  Backend API -> http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Frontend UI -> http://127.0.0.1:5500" -ForegroundColor Green

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:5500"
Write-Host "`nDone. The app is opening in your browser. Close the two server windows to stop." -ForegroundColor Green
