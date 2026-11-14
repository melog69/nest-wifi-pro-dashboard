@echo off
title Push to GitHub
cd /d "%~dp0"

echo ========================================================
echo   Pushing Nest Wifi Pro Dashboard to GitHub
echo   Repository: https://github.com/melog69/nest-wifi-pro-dashboard
echo ========================================================
echo.

git push -u origin main

echo.
pause
