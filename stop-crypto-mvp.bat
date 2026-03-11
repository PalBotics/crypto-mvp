@echo off
echo Stopping crypto-mvp services...

REM Kill by window title (when started via start script)
taskkill /F /FI "WINDOWTITLE eq Collector*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq Paper Trader*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq Dashboard*" /T 2>nul

REM Kill by command line using PowerShell CimInstance (Windows 11)
powershell -Command "Get-CimInstance Win32_Process -Filter 'name=''python.exe''' | Where-Object {$_.CommandLine -like '*apps.collector.main*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -Command "Get-CimInstance Win32_Process -Filter 'name=''python.exe''' | Where-Object {$_.CommandLine -like '*apps.paper_trader.main*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -Command "Get-CimInstance Win32_Process -Filter 'name=''python.exe''' | Where-Object {$_.CommandLine -like '*apps.dashboard.main*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -Command "Get-CimInstance Win32_Process -Filter 'name=''python.exe''' | Where-Object {$_.CommandLine -like '*launch.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

REM Stop PostgreSQL container
docker stop crypto-mvp-postgres 2>nul

echo All services stopped.
pause
