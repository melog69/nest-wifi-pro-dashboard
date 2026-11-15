"""
auth_auto.py — 1-Click Automated Google Master Token Capture for Nest Wifi Pro.

Eliminates the need to open DevTools F12 or manually copy/paste cookies:
  1. Opens an official Google sign-in window via Microsoft Edge or Google Chrome
     with a temporary, isolated user profile and remote debugging enabled.
  2. The user signs into their Google account and completes 2FA in the normal browser.
  3. This script continuously monitors the session via Chrome DevTools Protocol (CDP).
  4. The exact moment Google issues the 'oauth_token' cookie, this script captures it,
     exchanges it for a long-lived Master Token via gpsoauth, and encrypts it with Windows DPAPI.
  5. The browser window closes automatically upon completion.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any

import aiohttp
import gpsoauth

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import credentials


def find_browser_exe() -> str | None:
    """Locate Microsoft Edge or Google Chrome on the local system."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    for name in ["msedge", "chrome", "google-chrome"]:
        p = shutil.which(name)
        if p:
            return p
    return None


async def capture_oauth_token(port: int, timeout_seconds: int = 300) -> str | None:
    """Connect to the browser via CDP WebSocket and poll for the oauth_token cookie."""
    json_url = f"http://127.0.0.1:{port}/json"
    start_time = time.time()
    ws_url = None

    # Step 1: Wait for the browser's debugging endpoint to become available
    while time.time() - start_time < 20:
        try:
            req = urllib.request.Request(json_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode())
                if data:
                    target = next((p for p in data if p.get("type") == "page"), data[0])
                    ws_url = target.get("webSocketDebuggerUrl")
                    if ws_url:
                        break
        except Exception:
            await asyncio.sleep(0.5)

    if not ws_url:
        print("  ✗ Could not connect to browser debugging interface.")
        return None

    print("  ✓ Connected to browser session. Waiting for sign-in...")
    print("  👉 Complete your Google login in the browser window.")

    # Step 2: Connect over WebSocket and poll for the oauth_token cookie
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, timeout=30) as ws:
            # Enable Network domain
            await ws.send_json({"id": 1, "method": "Network.enable"})

            req_id = 10
            while time.time() - start_time < timeout_seconds:
                req_id += 1
                await ws.send_json({
                    "id": req_id,
                    "method": "Network.getCookies",
                    "params": {"urls": ["https://accounts.google.com"]}
                })

                # Process messages until response to req_id arrives
                found_token = None
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            if payload.get("id") == req_id:
                                cookies = payload.get("result", {}).get("cookies", [])
                                for c in cookies:
                                    if c.get("name") == "oauth_token" and c.get("value"):
                                        found_token = c["value"]
                                        break
                                break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                    except asyncio.TimeoutError:
                        break

                if found_token:
                    return found_token

                await asyncio.sleep(1.0)

    return None


def run_auto_auth(email: str = "", android_id: str = "") -> dict[str, Any]:
    """Execute the full 1-click automated authentication flow."""
    browser_exe = find_browser_exe()
    if not browser_exe:
        return {
            "ok": False,
            "error": "No compatible browser (Edge or Chrome) found on this machine.",
        }

    if not email:
        email = input("  Enter your Google account email: ").strip()
        if not email:
            return {"ok": False, "error": "Email is required"}

    if not android_id:
        android_id = secrets.token_hex(8)

    # Use a high random port to avoid conflicts
    debug_port = 9222 + (os.getpid() % 500)
    temp_profile = tempfile.mkdtemp(prefix="nest_auth_profile_")

    url = "https://accounts.google.com/EmbeddedSetup"
    args = [
        browser_exe,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]

    print()
    print("=" * 64)
    print("  Google Nest Wifi Pro — 1-Click Automated Sign-In")
    print("=" * 64)
    print(f"  Browser   : {os.path.basename(browser_exe)}")
    print(f"  Account   : {email}")
    print(f"  Target    : {url}")
    print()
    print("  🚀 Launching official Google Sign-In window...")

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        oauth_token = asyncio.run(capture_oauth_token(debug_port, timeout_seconds=300))
        if not oauth_token:
            return {"ok": False, "error": "Authentication timed out or was closed by user."}

        print()
        print("  🎉 oauth_token cookie successfully captured automatically!")
        print("  ⏳ Exchanging for long-lived Master Token with Google...")

        exchange_result = gpsoauth.exchange_token(email, oauth_token, android_id)
        master_token = exchange_result.get("Token") or exchange_result.get("Auth")

        if not master_token:
            error_detail = exchange_result.get("Error") or str(exchange_result)
            return {"ok": False, "error": f"Token exchange failed: {error_detail}"}

        print("  ✓ Master Token successfully received!")
        print("  🔒 Encrypting credentials with Windows DPAPI...")

        saved = credentials.save_credentials(email, master_token, android_id)
        if not saved:
            return {"ok": False, "error": "Failed to encrypt credentials on disk."}

        print("  ✓ Credentials saved and encrypted to .credentials.enc")
        print()
        print("=" * 64)
        print("  AUTHENTICATION COMPLETE!")
        print("  Your Nest Wifi Pro dashboard is now connected and ready to run.")
        print("=" * 64)

        return {
            "ok": True,
            "message": "Authentication successful! Master token encrypted.",
            "email": email,
        }

    finally:
        # Terminate browser process and clean up temporary user data dir
        try:
            proc.terminate()
            proc.kill()
        except Exception:
            pass
        try:
            shutil.rmtree(temp_profile, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    email_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    res = run_auto_auth(email=email_arg)
    if not res.get("ok"):
        print(f"\n  ✗ Error: {res.get('error')}")
        sys.exit(1)
    sys.exit(0)
