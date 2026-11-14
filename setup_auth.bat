@echo off
title Nest Wifi Pro Auth Setup
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Setting up...
    C:\Users\edgarguzman\.local\bin\uv.exe venv
    C:\Users\edgarguzman\.local\bin\uv.exe pip install -r requirements.txt
)

".venv\Scripts\python.exe" auth_helper.py
pause
