@echo off
setlocal

echo Stopping crypto-mvp services...

taskkill /F /FI "WINDOWTITLE eq Collector*" /T
taskkill /F /FI "WINDOWTITLE eq Paper Trader*" /T
taskkill /F /FI "WINDOWTITLE eq Dashboard*" /T

wmic process where "commandline like '%%apps.collector.main%%'" delete
wmic process where "commandline like '%%apps.paper_trader.main%%'" delete
wmic process where "commandline like '%%apps.dashboard.main%%'" delete
wmic process where "commandline like '%%launch.py%%'" delete

docker stop crypto-mvp-postgres

echo All services stopped.
pause
