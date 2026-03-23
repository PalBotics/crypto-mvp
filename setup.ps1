$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Text)
    Write-Host "============================================================"
    Write-Host $Text
    Write-Host "============================================================"
}

function Write-Success {
    param([string]$Text)
    Write-Host "[done] $Text" -ForegroundColor Green
}

function Write-FailAndExit {
    param(
        [string]$WhatFailed,
        [string]$HowToFix
    )
    Write-Host "[error] $WhatFailed" -ForegroundColor Red
    if ($HowToFix) {
        Write-Host $HowToFix -ForegroundColor Red
    }
    exit 1
}

Write-Section "crypto-mvp  setup"

# 1) Check Python installation and version >= 3.11
try {
    $pythonVersionOutput = (& python --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "python --version returned non-zero exit code"
    }
}
catch {
    Write-FailAndExit "Python is not installed or not available on PATH." "Install Python 3.11+ from https://www.python.org/downloads/ and check 'Add Python to PATH', then re-run ./setup.ps1"
}

if ($pythonVersionOutput -notmatch 'Python[ ]+([0-9]+)[.]([0-9]+)[.]([0-9]+)') {
    Write-FailAndExit "Unable to parse Python version output: $pythonVersionOutput" "Open a new PowerShell window and run python --version to verify installation."
}

$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]

if (($pyMajor -lt 3) -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Write-FailAndExit "Python version is too old ($pythonVersionOutput)." "Install Python 3.11+ from https://www.python.org/downloads/ and re-run ./setup.ps1"
}

Write-Success "Python detected: $pythonVersionOutput"

# 2) Check Docker Desktop is running
try {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "docker info returned non-zero exit code"
    }
}
catch {
    Write-FailAndExit "Docker Desktop is not running." "Please start Docker Desktop and re-run ./setup.ps1"
}

Write-Success "Docker Desktop is running"

# 3) Create Python virtual environment
try {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "python -m venv failed"
    }
}
catch {
    Write-FailAndExit "Failed to create Python virtual environment." "Ensure Python is installed correctly, then run: python -m venv .venv"
}

Write-Success "Python venv created"

# 4) Install Python dependencies
try {
    & ./.venv/Scripts/pip.exe install -e .
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed"
    }
}
catch {
    Write-FailAndExit "Failed to install Python dependencies." "Check internet access and Python version compatibility, then run: ./.venv/Scripts/pip.exe install -e ."
}

Write-Success "Python dependencies installed"

# 5) Start PostgreSQL container
try {
    & docker-compose up -d postgres
    if ($LASTEXITCODE -ne 0) {
        throw "docker-compose up -d postgres failed"
    }
    Start-Sleep -Seconds 5
}
catch {
    Write-FailAndExit "Failed to start PostgreSQL container." "Check Docker Desktop and compose setup, then run: docker-compose up -d postgres"
}

Write-Success "PostgreSQL started"

# 6) Run database migrations
try {
    & ./.venv/Scripts/python.exe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "alembic upgrade head failed"
    }
}
catch {
    Write-FailAndExit "Failed to apply database migrations." "Verify PostgreSQL is running and DB settings are valid, then run: ./.venv/Scripts/python.exe -m alembic upgrade head"
}

Write-Success "Database migrations applied"

# 7) Check if .env exists
if (Test-Path -Path ".env") {
    Write-Success ".env file found"
}
else {
    Write-Host "[warning] .env file not found." -ForegroundColor Red
    Write-Host "Copy .env from your dev machine before starting services." -ForegroundColor Red
}

Write-Section "Setup complete!"
Write-Host "Next steps:"
Write-Host "  1. Copy your .env file to this folder (if not done)"
Write-Host "  2. Run: ./start-crypto-mvp.bat"
Write-Host "  3. Open http://localhost:8000"
Write-Host "============================================================"
