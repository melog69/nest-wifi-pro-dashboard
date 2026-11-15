@echo off
title Nest Wifi Pro Dashboard - 1-Click Google Sign-In
cd /d "%~dp0"
echo ========================================================
echo   Nest Wifi Pro Dashboard - 1-Click Google Sign-In
echo ========================================================
echo.
echo Launching automated sign-in wizard...
echo (No need to open DevTools F12 or copy cookies manually!)
echo.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" auth_auto.py
) else (
    python auth_auto.py
)
pause
