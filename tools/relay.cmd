@echo off
rem Job Radar laptop relay: what the JobRadarRelay scheduled task runs (hidden).
cd /d "%~dp0.."
set PYTHONUNBUFFERED=1
echo. >> "data\relay.log"
echo ===== %date% %time% ===== >> "data\relay.log"
python -m radar.main relay --push >> "data\relay.log" 2>&1
