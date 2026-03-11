@echo off
setlocal

echo Stopping crypto-mvp services...

taskkill /F /FI "WINDOWTITLE eq Collector*" /T
taskkill /F /FI "WINDOWTITLE eq Paper Trader*" /T
taskkill /F /FI "WINDOWTITLE eq Dashboard*" /T

docker stop crypto-mvp-postgres

echo All services stopped.
pause
