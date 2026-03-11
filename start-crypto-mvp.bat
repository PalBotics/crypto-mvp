@echo off
setlocal

echo Starting crypto-mvp...

docker info >nul 2>&1
if errorlevel 1 (
    echo Docker not running. Launching Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

    set /a WAIT_COUNT=0
    :wait_docker
    if %WAIT_COUNT% GEQ 10 goto docker_timeout
    timeout /t 3 /nobreak >nul
    <nul set /p =.
    docker info >nul 2>&1
    if not errorlevel 1 goto docker_ready
    set /a WAIT_COUNT+=1
    goto wait_docker

    :docker_timeout
    echo.
    echo Docker did not become ready within 30 seconds.
    goto after_docker_check

    :docker_ready
    echo.
    echo Docker is ready.
)

:after_docker_check
cd /d "%~dp0"

docker-compose up -d postgres
if errorlevel 1 (
    docker start crypto-mvp-postgres >nul 2>&1
)
echo PostgreSQL started

timeout /t 3 /nobreak >nul

start "Collector" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .\.venv\Scripts\Activate.ps1; python -m apps.collector.main"
start "Paper Trader" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .\.venv\Scripts\Activate.ps1; python -m apps.paper_trader.main"
start "Dashboard" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .\.venv\Scripts\Activate.ps1; python launch.py"

echo All services started. Dashboard at http://localhost:8000
pause
