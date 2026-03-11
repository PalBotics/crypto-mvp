@echo off
echo Starting crypto-mvp...
echo.

REM Check Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo Docker is not running.
    echo Please start Docker Desktop, wait for it to fully
    echo load, then press any key to continue...
    pause
)

REM Start PostgreSQL
echo Starting PostgreSQL...
cd /d C:\Users\Paul\Apps\crypto-mvp
docker-compose up -d postgres
if errorlevel 1 (
    docker start crypto-mvp-postgres
)
echo PostgreSQL started.
timeout /t 3 /nobreak >nul

REM Start services in named windows
echo Starting services...
start "Collector" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .venv\Scripts\activate; python -m apps.collector.main"
start "Paper Trader" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .venv\Scripts\activate; python -m apps.paper_trader.main"
start "Dashboard" powershell -NoExit -Command "cd C:\Users\Paul\Apps\crypto-mvp; .venv\Scripts\activate; python launch.py"

echo.
echo All services started.
echo Dashboard at http://localhost:8000
echo.
pause
