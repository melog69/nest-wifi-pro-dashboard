@echo off
title Install Nest Wifi Pro Background Service
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py --install-service
) else (
    python run.py --install-service
)
pause
