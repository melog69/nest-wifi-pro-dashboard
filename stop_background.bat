@echo off
title Stop Nest Wifi Pro Dashboard
cd /d "%~dp0"
echo Stopping Nest Wifi Pro Dashboard on port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') do (
    echo Terminating PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)
echo Dashboard stopped.
