@echo off
title Nest Wifi Pro Dashboard (Background Launcher)
cd /d "%~dp0"
echo Starting Nest Wifi Pro Dashboard in background...
wscript.exe "%~dp0start_background.vbs"
echo Dashboard launched in background on http://localhost:5000
