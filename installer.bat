@echo off
setlocal EnableDelayedExpansion
title Nest Wifi Pro Dashboard - Server Installer
color 0A

echo ========================================================
echo        Nest Wifi Pro Dashboard - Server Installer
echo ========================================================
echo.
echo Installing Nest Wifi Pro Dashboard on this server...
echo.

:: 1. Determine destination folder
if defined LOCALAPPDATA (
    set "INSTALL_DIR=%LOCALAPPDATA%\NestWifiProDashboard"
) else (
    set "INSTALL_DIR=C:\NestWifiProDashboard"
)

echo [1/5] Installation directory: "!INSTALL_DIR!"
if not exist "!INSTALL_DIR!" mkdir "!INSTALL_DIR!"
if not exist "!INSTALL_DIR!\static" mkdir "!INSTALL_DIR!\static"

:: 2. Copy payload files from extraction directory
echo [2/5] Copying application files...
set "SRC=%~dp0"

copy /y "%SRC%app.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%config.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%credentials.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%service_manager.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%wifi_client.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%auth_helper.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%run.py" "!INSTALL_DIR!\" >nul
copy /y "%SRC%requirements.txt" "!INSTALL_DIR!\" >nul
copy /y "%SRC%.env.example" "!INSTALL_DIR!\" >nul
if exist "%SRC%LICENSE" copy /y "%SRC%LICENSE" "!INSTALL_DIR!\" >nul
if exist "%SRC%README.md" copy /y "%SRC%README.md" "!INSTALL_DIR!\" >nul

copy /y "%SRC%start.bat" "!INSTALL_DIR!\" >nul
copy /y "%SRC%start_background.vbs" "!INSTALL_DIR!\" >nul
copy /y "%SRC%start_background.bat" "!INSTALL_DIR!\" >nul
copy /y "%SRC%stop_background.bat" "!INSTALL_DIR!\" >nul
copy /y "%SRC%install_service.bat" "!INSTALL_DIR!\" >nul
copy /y "%SRC%uninstall_service.bat" "!INSTALL_DIR!\" >nul

:: Static frontend files
if exist "%SRC%static_index.html" (
    copy /y "%SRC%static_index.html" "!INSTALL_DIR!\static\index.html" >nul
) else if exist "%SRC%static\index.html" (
    copy /y "%SRC%static\index.html" "!INSTALL_DIR!\static\index.html" >nul
)

if exist "%SRC%static_settings.html" (
    copy /y "%SRC%static_settings.html" "!INSTALL_DIR!\static\settings.html" >nul
) else if exist "%SRC%static\settings.html" (
    copy /y "%SRC%static\settings.html" "!INSTALL_DIR!\static\settings.html" >nul
)

:: Create .env if missing
if not exist "!INSTALL_DIR!\.env" (
    if exist "!INSTALL_DIR!\.env.example" (
        copy /y "!INSTALL_DIR!\.env.example" "!INSTALL_DIR!\.env" >nul
    )
)

:: 3. Python environment detection & setup
echo [3/5] Setting up Python environment...
set "PYTHON_EXE="

:: Check if virtual environment already exists
if exist "!INSTALL_DIR!\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=!INSTALL_DIR!\.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%p in ('where python') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
        )
    ) else (
        where py >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=py"
        )
    )
)

if not defined PYTHON_EXE (
    echo.
    echo [!] Python was not detected on this machine.
    echo Attempting to install Python 3.11 via winget...
    winget install --id Python.Python.3.11 -e --source winget
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%p in ('where python') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
        )
    )
)

if not defined PYTHON_EXE (
    echo.
    echo [!] Could not automatically install Python.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo and run "!INSTALL_DIR!\start.bat".
    pause
    exit /b 1
)

:: Create virtual environment if missing
if not exist "!INSTALL_DIR!\.venv\Scripts\python.exe" (
    echo Creating virtual environment in !INSTALL_DIR!\.venv...
    where uv >nul 2>&1
    if !errorlevel! equ 0 (
        uv venv "!INSTALL_DIR!\.venv"
    ) else (
        "!PYTHON_EXE!" -m venv "!INSTALL_DIR!\.venv"
    )
)

:: Install dependencies
echo Installing requirements...
where uv >nul 2>&1
if !errorlevel! equ 0 (
    uv pip install -r "!INSTALL_DIR!\requirements.txt" --python "!INSTALL_DIR!\.venv\Scripts\python.exe" --quiet
) else (
    "!INSTALL_DIR!\.venv\Scripts\python.exe" -m ensurepip --default-pip >nul 2>&1
    "!INSTALL_DIR!\.venv\Scripts\python.exe" -m pip install -r "!INSTALL_DIR!\requirements.txt" --quiet
)

:: 4. Background Service & Shortcuts
echo [4/5] Registering background service & shortcuts...
cd /d "!INSTALL_DIR!"
"!INSTALL_DIR!\.venv\Scripts\python.exe" run.py --install-service

:: Create Desktop Shortcut via VBScript
set "VBS_SHORTCUT=%TEMP%\create_shortcut_%RANDOM%.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > "!VBS_SHORTCUT!"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\Nest Wifi Dashboard.lnk" >> "!VBS_SHORTCUT!"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "!VBS_SHORTCUT!"
echo oLink.TargetPath = "!INSTALL_DIR!\start_background.vbs" >> "!VBS_SHORTCUT!"
echo oLink.WorkingDirectory = "!INSTALL_DIR!" >> "!VBS_SHORTCUT!"
echo oLink.Description = "Nest Wifi Pro Dashboard" >> "!VBS_SHORTCUT!"
echo oLink.Save >> "!VBS_SHORTCUT!"
cscript //nologo "!VBS_SHORTCUT!" >nul 2>&1
del "!VBS_SHORTCUT!" >nul 2>&1

:: 5. Launch service
echo [5/5] Starting background service...
wscript.exe "!INSTALL_DIR!\start_background.vbs"

echo.
echo ========================================================
echo   Nest Wifi Pro Dashboard successfully installed!
echo ========================================================
echo.
echo Installed Location : !INSTALL_DIR!
echo Dashboard URL      : http://localhost:5000
echo Autostart          : Active (Starts silently on server boot)
echo Desktop Shortcut   : Created on Desktop
echo.
echo Opening dashboard in your default browser...
start http://localhost:5000
timeout /t 3 >nul
