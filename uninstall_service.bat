@echo off
title Uninstall Nest Wifi Pro Background Service
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py --uninstall-service
) else (
    python run.py --uninstall-service
)
pause
