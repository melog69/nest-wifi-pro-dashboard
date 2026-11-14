@echo off
title Nest Wifi Pro Dashboard
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Creating it now...
    C:\Users\edgarguzman\.local\bin\uv.exe venv
    C:\Users\edgarguzman\.local\bin\uv.exe pip install -r requirements.txt
)

echo Starting Nest Wifi Pro Dashboard...
".venv\Scripts\python.exe" run.py
pause
