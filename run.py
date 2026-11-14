#!/usr/bin/env python3
"""
run.py — Entry point for the Nest Wifi Pro Dashboard.

What it does:
  1. Checks for a .env file; copies .env.example if missing.
  2. Prints a startup banner with configuration info.
  3. Indicates whether the app is running in DEMO or LIVE mode.
  4. Opens the default web browser to the dashboard URL.
  5. Starts the Flask development server.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser

# ---------------------------------------------------------------------------
# Ensure the working directory is the project root so imports work
# ---------------------------------------------------------------------------
_project_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_project_dir)
sys.path.insert(0, _project_dir)

# ---------------------------------------------------------------------------
# .env bootstrap
# ---------------------------------------------------------------------------
_env_file = os.path.join(_project_dir, ".env")
_env_example = os.path.join(_project_dir, ".env.example")

if not os.path.exists(_env_file):
    if os.path.exists(_env_example):
        shutil.copy2(_env_example, _env_file)
        print(f"  ℹ  Created .env from .env.example — edit it with your credentials.")
    else:
        print("  ⚠  No .env or .env.example found.  Running with defaults (demo mode).")

# NOW it's safe to import config (which calls load_dotenv)
import config  # noqa: E402

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
_BANNER = r"""
 ╔══════════════════════════════════════════════════════════╗
 ║       🏠  Nest Wifi Pro Dashboard                       ║
 ║                                                          ║
 ║   A local web UI for monitoring & managing your          ║
 ║   Google Nest Wifi Pro mesh network.                     ║
 ╚══════════════════════════════════════════════════════════╝
"""


def _print_banner() -> None:
    print(_BANNER)

    mode = "DEMO" if config.is_demo_mode() else "LIVE"
    mode_color = "\033[93m" if config.is_demo_mode() else "\033[92m"
    reset = "\033[0m"

    print(f"  Mode           : {mode_color}{mode}{reset}")
    if config.is_demo_mode():
        print("                   (No credentials configured — using mock data)")
        print("                   Authenticate in Settings or run 'python auth_helper.py'.")
    else:
        print(f"  Google account : {config.GOOGLE_EMAIL}")
        import credentials
        st = credentials.get_status()
        if st.get("encrypted"):
            print(f"  Token storage  : \033[92m🔒 {st.get('cipher')}\033[0m")

    print(f"  Router IP      : {config.ROUTER_IP}")
    print(f"  Server port    : {config.FLASK_PORT}")
    print(f"  Refresh rate   : {config.REFRESH_INTERVAL}s")
    print()


# ---------------------------------------------------------------------------
# Browser auto-open (in a background thread with a small delay)
# ---------------------------------------------------------------------------
def _open_browser(port: int) -> None:
    """Wait for Flask to spin up, then open the dashboard in the browser."""
    time.sleep(1.5)
    url = f"http://localhost:{port}"
    print(f"  🌐  Opening {url} in your default browser…\n")
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _print_banner()

    # Ensure static directory exists (even if empty — Flask needs it)
    static_dir = os.path.join(_project_dir, "static")
    os.makedirs(static_dir, exist_ok=True)

    # Check for index.html
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        # Create a minimal placeholder so Flask doesn't 404
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(
                "<!DOCTYPE html>\n<html><head><title>Nest Wifi Dashboard</title></head>\n"
                "<body style=\"font-family:system-ui;display:flex;align-items:center;"
                "justify-content:center;height:100vh;margin:0;background:#1a1a2e;"
                "color:#e0e0e0\">\n"
                "<div style=\"text-align:center\">\n"
                "<h1>🏠 Nest Wifi Pro Dashboard</h1>\n"
                "<p>Backend is running! The frontend has not been built yet.</p>\n"
                "<p style=\"color:#888\">API available at <code>/api/status</code>, "
                "<code>/api/devices</code>, etc.</p>\n"
                "</div></body></html>\n"
            )

    # Open browser in background
    browser_thread = threading.Thread(target=_open_browser, args=(config.FLASK_PORT,), daemon=True)
    browser_thread.start()

    # Start Flask
    print(f"  🚀  Starting Flask on http://0.0.0.0:{config.FLASK_PORT}")
    print("  ─" * 30)
    print()

    from app import app  # noqa: E402
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
