"""
config.py — Configuration management for the Nest Wifi Pro Dashboard.

Loads settings from a .env file (via python-dotenv) and exposes them as
module-level constants.  Sensible defaults are provided for every optional
setting; only GOOGLE_EMAIL and GOOGLE_MASTER_TOKEN are truly required for
live mode.
"""

import os
import secrets

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from the project root (next to this file)
# ---------------------------------------------------------------------------
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path)

import credentials

# ---------------------------------------------------------------------------
# Google account credentials (loaded from encrypted store or .env)
# ---------------------------------------------------------------------------
GOOGLE_EMAIL: str = os.getenv("GOOGLE_EMAIL", "").strip()
GOOGLE_MASTER_TOKEN: str = os.getenv("GOOGLE_MASTER_TOKEN", "").strip()
ANDROID_ID: str = os.getenv("ANDROID_ID", "").strip() or secrets.token_hex(8)

# Load from encrypted store if available
_creds = credentials.load_credentials()
if not _creds and GOOGLE_EMAIL and GOOGLE_MASTER_TOKEN:
    credentials.migrate_from_env()
    _creds = credentials.load_credentials()

if _creds:
    GOOGLE_EMAIL = _creds.get("google_email") or GOOGLE_EMAIL
    GOOGLE_MASTER_TOKEN = _creds.get("google_master_token") or GOOGLE_MASTER_TOKEN
    ANDROID_ID = _creds.get("android_id") or ANDROID_ID


def reload_credentials() -> None:
    """Reload credentials from encrypted storage into config constants."""
    global GOOGLE_EMAIL, GOOGLE_MASTER_TOKEN, ANDROID_ID
    c = credentials.load_credentials()
    if c:
        GOOGLE_EMAIL = c.get("google_email") or GOOGLE_EMAIL
        GOOGLE_MASTER_TOKEN = c.get("google_master_token") or GOOGLE_MASTER_TOKEN
        ANDROID_ID = c.get("android_id") or ANDROID_ID
    else:
        GOOGLE_MASTER_TOKEN = ""

# ---------------------------------------------------------------------------
# Network / router settings
# ---------------------------------------------------------------------------
ROUTER_IP: str = os.getenv("ROUTER_IP", "192.168.86.1").strip()

# ---------------------------------------------------------------------------
# Flask server settings
# ---------------------------------------------------------------------------
FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))

# ---------------------------------------------------------------------------
# Data-refresh interval (seconds) used by the caching layer
# ---------------------------------------------------------------------------
REFRESH_INTERVAL: int = int(os.getenv("REFRESH_INTERVAL", "30"))

# ---------------------------------------------------------------------------
# Demo / mock mode
# ---------------------------------------------------------------------------
FORCE_DEMO_MODE: bool = os.getenv("FORCE_DEMO_MODE", "false").strip().lower() in (
    "true",
    "1",
    "yes",
)


def has_credentials() -> bool:
    """Return True if the minimum credentials for live mode are present."""
    return bool(GOOGLE_EMAIL) and bool(GOOGLE_MASTER_TOKEN)


def is_demo_mode() -> bool:
    """Return True when the app should run with mock/demo data."""
    return FORCE_DEMO_MODE or not has_credentials()


# ---------------------------------------------------------------------------
# Quick sanity-check when the module is executed directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Nest Wifi Dashboard — Configuration ===")
    print(f"  GOOGLE_EMAIL        : {'(set)' if GOOGLE_EMAIL else '(not set)'}")
    print(f"  GOOGLE_MASTER_TOKEN : {'(set)' if GOOGLE_MASTER_TOKEN else '(not set)'}")
    print(f"  ANDROID_ID          : {ANDROID_ID}")
    print(f"  ROUTER_IP           : {ROUTER_IP}")
    print(f"  FLASK_PORT          : {FLASK_PORT}")
    print(f"  REFRESH_INTERVAL    : {REFRESH_INTERVAL}s")
    print(f"  FORCE_DEMO_MODE     : {FORCE_DEMO_MODE}")
    print(f"  Demo mode active?   : {is_demo_mode()}")
