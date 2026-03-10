# rebuild_dashboard.ps1
# Rebuilds the React frontend and relaunches the dashboard window.
# Run from repo root: .\rebuild_dashboard.ps1

param(
    [switch]$NoLaunch  # Pass -NoLaunch to build only, skip relaunch
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $RepoRoot "apps\dashboard\frontend"
$DistDir = Join-Path $FrontendDir "dist"
$Venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== crypto-mvp dashboard rebuild ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Check npm is available ---
Write-Host "[1/4] Checking dependencies..." -ForegroundColor Yellow
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm not found. Is Node.js installed and on PATH?"
    exit 1
}
if (-not (Test-Path $Venv)) {
    Write-Error "Python venv not found at $Venv"
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# --- Step 2: Install/update npm dependencies if needed ---
Write-Host "[2/4] Checking npm dependencies..." -ForegroundColor Yellow
$NodeModules = Join-Path $FrontendDir "node_modules"
if (-not (Test-Path $NodeModules)) {
    Write-Host "      node_modules missing, running npm install..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install
    Pop-Location
} else {
    Write-Host "      node_modules present, skipping install" -ForegroundColor Green
}

# --- Step 3: Build frontend ---
Write-Host "[3/4] Building frontend..." -ForegroundColor Yellow
Push-Location $FrontendDir
try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "npm run build failed with exit code $LASTEXITCODE"
        exit 1
    }
} finally {
    Pop-Location
}

if (-not (Test-Path $DistDir)) {
    Write-Error "Build succeeded but dist/ not found at $DistDir"
    exit 1
}
Write-Host "      Build complete -> $DistDir" -ForegroundColor Green

# --- Step 4: Relaunch dashboard ---
if ($NoLaunch) {
    Write-Host ""
    Write-Host "=== Build complete. Skipping launch (-NoLaunch flag set). ===" -ForegroundColor Cyan
    exit 0
}

Write-Host "[4/4] Launching dashboard..." -ForegroundColor Yellow

# Kill any existing dashboard process to avoid port conflicts
$existing = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*dashboard*" -or $_.CommandLine -like "*launch*"
}
if ($existing) {
    Write-Host "      Stopping existing dashboard process (PID $($existing.Id))..." -ForegroundColor Yellow
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# Launch via launch.py if it exists, otherwise fall back to dashboard main
$LaunchScript = Join-Path $RepoRoot "launch.py"
$DashboardMain = "apps.dashboard.main"

if (Test-Path $LaunchScript) {
    Write-Host "      Starting via launch.py..." -ForegroundColor Green
    Start-Process -FilePath $Venv -ArgumentList $LaunchScript -WorkingDirectory $RepoRoot
} else {
    Write-Host "      launch.py not found, starting FastAPI directly..." -ForegroundColor Yellow
    Write-Host "      Dashboard will be available at http://localhost:8000" -ForegroundColor Cyan
    Start-Process -FilePath $Venv -ArgumentList "-m", $DashboardMain -WorkingDirectory $RepoRoot
}

Write-Host ""
Write-Host "=== Done. Dashboard launching. ===" -ForegroundColor Cyan
Write-Host ""