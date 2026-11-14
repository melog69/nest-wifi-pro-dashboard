@echo off
title Build Nest Wifi Pro Dashboard Windows Installer
cd /d "%~dp0"
echo Building Windows Self-Extracting Executable (SFX)...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" build_installer.py
) else (
    python build_installer.py
)
pause
