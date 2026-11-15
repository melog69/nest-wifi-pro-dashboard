"""
service_manager.py — Background service and autostart management for Nest Wifi Pro Dashboard.

Provides:
  - Windows silent background execution via pythonw.exe & VBScript.
  - Windows Startup folder autostart registration (zero admin privileges required).
  - Native helper batch files: start_background.bat, stop_background.bat,
    install_service.bat, uninstall_service.bat.
  - Service state inspection (port check, process PID discovery).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from typing import Any

import config

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_pythonw_exe() -> str:
    """Return the absolute path to pythonw.exe (windowless python on Windows)."""
    # 1. Prefer virtualenv pythonw
    venv_pythonw = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pythonw.exe")
    if os.path.exists(venv_pythonw):
        return venv_pythonw

    # 2. Virtualenv python (non-w)
    venv_python = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python

    # 3. Check current sys.executable directory for pythonw
    current_dir = os.path.dirname(sys.executable)
    sibling_pythonw = os.path.join(current_dir, "pythonw.exe")
    if os.path.exists(sibling_pythonw):
        return sibling_pythonw

    return sys.executable


def get_startup_file_path() -> str | None:
    """Return the path where the autostart link/file lives for this user."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            startup_dir = os.path.join(
                appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
            )
            os.makedirs(startup_dir, exist_ok=True)
            return os.path.join(startup_dir, "NestWifiProDashboard.vbs")
    elif sys.platform == "linux":
        autostart_dir = os.path.expanduser("~/.config/autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        return os.path.join(autostart_dir, "nest-wifi-dashboard.desktop")
    return None


def is_port_listening(port: int) -> bool:
    """Quickly check if the server port is open and listening locally."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.6)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def get_listening_pid(port: int) -> int | None:
    """Find the process ID listening on the given port on Windows."""
    if sys.platform != "win32":
        return None
    try:
        cmd = f'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"'
        res = subprocess.check_output(cmd, shell=True, text=True, timeout=3).strip()
        if res:
            pids = [int(p) for p in res.split() if p.isdigit()]
            if pids:
                return pids[0]
    except Exception:
        pass

    try:
        cmd = f"netstat -ano | findstr :{port}"
        output = subprocess.check_output(cmd, shell=True, text=True, timeout=3)
        for line in output.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5 and "LISTENING" in line:
                return int(parts[-1])
    except Exception:
        pass
    return None


def ensure_launcher_scripts() -> dict[str, str]:
    """Create or update start_background.vbs, start_background.bat, and stop_background.bat."""
    pythonw = get_pythonw_exe()
    port = config.FLASK_PORT

    # 1. start_background.vbs (silent windowless launcher)
    vbs_path = os.path.join(PROJECT_DIR, "start_background.vbs")
    vbs_content = f'''\' Nest Wifi Pro Dashboard - Headless Background Runner
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "{PROJECT_DIR}"
WshShell.Run Chr(34) & "{pythonw}" & Chr(34) & " run.py --no-browser", 0, False
Set WshShell = Nothing
'''
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs_content)

    # 2. start_background.bat (batch launcher)
    bat_start = os.path.join(PROJECT_DIR, "start_background.bat")
    bat_start_content = f"""@echo off
title Nest Wifi Pro Dashboard (Background Launcher)
cd /d "%~dp0"
echo Starting Nest Wifi Pro Dashboard in background...
wscript.exe "%~dp0start_background.vbs"
echo Dashboard launched in background on http://localhost:{port}
"""
    with open(bat_start, "w", encoding="utf-8") as f:
        f.write(bat_start_content)

    # 3. stop_background.bat
    bat_stop = os.path.join(PROJECT_DIR, "stop_background.bat")
    bat_stop_content = f"""@echo off
title Stop Nest Wifi Pro Dashboard
cd /d "%~dp0"
echo Stopping Nest Wifi Pro Dashboard on port {port}...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :{port} ^| findstr LISTENING') do (
    echo Terminating PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)
echo Dashboard stopped.
"""
    with open(bat_stop, "w", encoding="utf-8") as f:
        f.write(bat_stop_content)

    # 4. install_service.bat
    bat_inst = os.path.join(PROJECT_DIR, "install_service.bat")
    bat_inst_content = """@echo off
title Install Nest Wifi Pro Background Service
cd /d "%~dp0"
if exist ".venv\\Scripts\\python.exe" (
    ".venv\\Scripts\\python.exe" run.py --install-service
) else (
    python run.py --install-service
)
pause
"""
    with open(bat_inst, "w", encoding="utf-8") as f:
        f.write(bat_inst_content)

    # 5. uninstall_service.bat
    bat_uninst = os.path.join(PROJECT_DIR, "uninstall_service.bat")
    bat_uninst_content = """@echo off
title Uninstall Nest Wifi Pro Background Service
cd /d "%~dp0"
if exist ".venv\\Scripts\\python.exe" (
    ".venv\\Scripts\\python.exe" run.py --uninstall-service
) else (
    python run.py --uninstall-service
)
pause
"""
    with open(bat_uninst, "w", encoding="utf-8") as f:
        f.write(bat_uninst_content)

    return {
        "vbs_path": vbs_path,
        "bat_start": bat_start,
        "bat_stop": bat_stop,
        "bat_inst": bat_inst,
        "bat_uninst": bat_uninst,
    }


def is_autostart_enabled() -> bool:
    """Return True if the startup launcher file is currently installed."""
    p = get_startup_file_path()
    return bool(p and os.path.exists(p))


def enable_autostart() -> dict[str, Any]:
    """Register the application to run silently on Windows login."""
    try:
        scripts = ensure_launcher_scripts()
        startup_path = get_startup_file_path()
        if not startup_path:
            return {"ok": False, "error": "Could not determine system startup folder path."}

        vbs_launcher = scripts["vbs_path"]
        content = f'''\' Nest Wifi Pro Dashboard - System Startup Launcher
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run Chr(34) & "wscript.exe" & Chr(34) & " " & Chr(34) & "{vbs_launcher}" & Chr(34), 0, False
Set WshShell = Nothing
'''
        with open(startup_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "ok": True,
            "message": "Background service successfully registered for Windows startup.",
            "startup_path": startup_path,
        }
    except PermissionError:
        return {
            "ok": False,
            "permission_required": True,
            "error": "Access to Windows Startup folder was restricted. Please run install_service.bat directly to register startup.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def disable_autostart() -> dict[str, Any]:
    """Unregister the application from system startup."""
    try:
        startup_path = get_startup_file_path()
        if startup_path and os.path.exists(startup_path):
            os.remove(startup_path)
            return {"ok": True, "message": "Background service autostart successfully disabled."}
        return {"ok": True, "message": "Autostart was not active."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_service_status() -> dict[str, Any]:
    """Return complete status information for the background service."""
    port = config.FLASK_PORT
    listening = is_port_listening(port)
    pid = get_listening_pid(port) if listening else None
    autostart = is_autostart_enabled()
    pythonw = get_pythonw_exe()
    current_pid = os.getpid()

    return {
        "ok": True,
        "service_name": "Nest Wifi Pro Dashboard",
        "running": listening,
        "autostart": autostart,
        "port": port,
        "url": f"http://localhost:{port}",
        "pid": pid or (current_pid if listening else None),
        "current_pid": current_pid,
        "platform": sys.platform,
        "python_path": pythonw,
        "project_dir": PROJECT_DIR,
        "startup_path": get_startup_file_path(),
    }


def start_background_service() -> dict[str, Any]:
    """Launch the dashboard in the background if not already running."""
    port = config.FLASK_PORT
    if is_port_listening(port):
        pid = get_listening_pid(port)
        return {
            "ok": True,
            "message": f"Dashboard is already running on port {port} (PID: {pid}).",
            "already_running": True,
        }

    ensure_launcher_scripts()
    vbs_path = os.path.join(PROJECT_DIR, "start_background.vbs")

    try:
        if sys.platform == "win32":
            subprocess.Popen(["wscript.exe", vbs_path], shell=False)
        else:
            python_exe = sys.executable
            subprocess.Popen(
                [python_exe, "run.py", "--no-browser"],
                cwd=PROJECT_DIR,
                start_new_session=True,
            )
        return {"ok": True, "message": f"Background service launched on http://localhost:{port}"}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to start background service: {exc}"}


def stop_background_service() -> dict[str, Any]:
    """Terminate the process running on config.FLASK_PORT."""
    port = config.FLASK_PORT
    pid = get_listening_pid(port)
    if not pid:
        if is_port_listening(port):
            pid = os.getpid()
        else:
            return {"ok": True, "message": "Service is not currently running."}

    try:
        if pid == os.getpid():
            import threading
            import time

            def delayed_kill():
                time.sleep(0.5)
                if sys.platform == "win32":
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, check=False)
                else:
                    os.kill(pid, signal.SIGTERM)

            threading.Thread(target=delayed_kill, daemon=True).start()
            return {"ok": True, "message": f"Service process (PID {pid}) stopping."}

        if sys.platform == "win32":
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
        return {"ok": True, "message": f"Service process (PID {pid}) stopped."}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to stop process {pid}: {exc}"}
