#!/usr/bin/env python3
"""
auth_helper.py — Interactive helper to obtain a Google master token.

The Google Nest / Home APIs require a *master token* to authenticate.
This script walks you through the process:

  1.  Open a special Google OAuth URL in your browser.
  2.  Sign in and authorise the app.
  3.  Copy the resulting oauth_token from the browser.
  4.  The script exchanges it for a long-lived master token via gpsoauth.
  5.  The master token is saved into your .env file automatically.

Usage:
    python auth_helper.py
"""

import os
import sys
import webbrowser

try:
    import gpsoauth  # type: ignore
except ImportError:
    print("ERROR: gpsoauth is not installed.  Run:  pip install gpsoauth")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_EMBEDDED_SETUP_URL = "https://accounts.google.com/EmbeddedSetup"
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_ENV_EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.example")


def _ensure_env_file() -> None:
    """Create .env from .env.example if it doesn't exist yet."""
    if not os.path.exists(_ENV_FILE):
        if os.path.exists(_ENV_EXAMPLE):
            import shutil
            shutil.copy2(_ENV_EXAMPLE, _ENV_FILE)
            print(f"  Created {_ENV_FILE} from .env.example")
        else:
            with open(_ENV_FILE, "w", encoding="utf-8") as f:
                f.write("GOOGLE_EMAIL=\nGOOGLE_MASTER_TOKEN=\n")
            print(f"  Created minimal {_ENV_FILE}")


def _update_env(key: str, value: str) -> None:
    """Insert or update a KEY=value line in the .env file."""
    _ensure_env_file()
    lines: list[str] = []
    found = False
    with open(_ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
                lines.append(f"{key}={value}\n")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(_ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main() -> None:
    """Run the interactive master-token flow."""
    print()
    print("=" * 64)
    print("  Google Nest Wifi Pro Dashboard — Authentication Setup")
    print("=" * 64)
    print()
    print("  Google deprecated the old OOB login page (Error 400).")
    print("  We now use Google's official EmbeddedSetup cookie method.")
    print()

    # Step 1 — email
    email = input("  1. Enter your Google account email: ").strip()
    if not email:
        print("  ✗ Email is required.")
        sys.exit(1)

    # Step 2 — Android ID
    import secrets
    default_android_id = secrets.token_hex(8)
    android_id_input = input(
        f"  2. Android ID (press ENTER to use [{default_android_id}]): "
    ).strip()
    android_id = android_id_input or default_android_id

    # Step 3 — Choose sign-in method
    print()
    print("  Choose sign-in method:")
    print("    [1] (Recommended) 1-Click Automated Sign-In (zero DevTools / zero copy-pasting)")
    print("    [2] Manual Entry (DevTools / Cookie-Editor extension)")
    choice = input("  Select [1 or 2, default=1]: ").strip() or "1"

    if choice == "1":
        try:
            import auth_auto
            res = auth_auto.run_auto_auth(email=email, android_id=android_id)
            if res.get("ok"):
                print("  ✓ Authentication successful!")
                sys.exit(0)
            else:
                print(f"  ✗ Automated login failed: {res.get('error')}")
                print("  Falling back to manual method...\n")
        except Exception as exc:
            print(f"  ⚠ Could not run automated helper ({exc}). Falling back to manual method...\n")

    # Step 4 — Embedded setup instructions (Manual fallback)
    print()
    print("  " + "─" * 60)
    print("  Manual Step: Get your oauth_token cookie")
    print("  " + "─" * 60)
    print("  1. A browser window will open to:")
    print("     https://accounts.google.com/EmbeddedSetup")
    print()
    print("  2. Sign in with your Google account and complete 2FA.")
    print("  3. Click 'I agree' on any prompt.")
    print("  4. When you see a loading or blank page, get the 'oauth_token' cookie via:")
    print("     • FASTEST: Use the 'Cookie-Editor' browser extension (1-click copy).")
    print("     • DEVTOOLS: Press F12 -> Application -> Cookies -> accounts.google.com -> oauth_token.")
    print("  5. Copy its Value (starts with oauth2_4/...) and paste it below.")
    print("  " + "─" * 60)
    print()

    input("  Press ENTER to open your browser to EmbeddedSetup...")
    webbrowser.open(_EMBEDDED_SETUP_URL)

    print()
    oauth_token = input("  Paste the 'oauth_token' cookie value here: ").strip()
    if not oauth_token:
        print("  ✗ No token provided — aborting.")
        sys.exit(1)

    # Clean up any surrounding quotes or spaces
    oauth_token = oauth_token.strip("'\" \t\r\n")

    # Step 4 — Exchange for master token
    print()
    print("  Exchanging oauth_token for long-lived Master Token...")
    try:
        result = gpsoauth.exchange_token(email, oauth_token, android_id)
    except Exception as exc:
        print(f"  ✗ Token exchange failed: {exc}")
        sys.exit(1)

    master_token = result.get("Token") or result.get("Auth")
    if not master_token:
        print(f"  ✗ Unexpected response from Google: {result}")
        print()
        print("  Tips:")
        print("    • The oauth_token cookie is single-use and expires in ~5 minutes.")
        print("    • Make sure you copy the entire Value column without spaces.")
        sys.exit(1)

    print(f"  ✓ Master token successfully obtained! ({master_token[:14]}...)")

    # Step 5 — Save encrypted credentials
    print()
    import credentials
    saved = credentials.save_credentials(email, master_token, android_id)
    if saved:
        print(f"  ✓ Token successfully encrypted using {credentials._CIPHER_NAME}")
        print(f"  ✓ Saved to .credentials.enc (no plaintext tokens stored in .env)")
    else:
        print(f"  ⚠ Failed to write encrypted file; falling back to .env")
        _update_env("GOOGLE_EMAIL", email)
        _update_env("GOOGLE_MASTER_TOKEN", master_token)
        _update_env("ANDROID_ID", android_id)
    print()
    print("  You're all set! Now run start.bat to launch your live dashboard.")
    print("  (You can also manage or refresh your Google credentials in the Settings tab at any time).")
    print()


if __name__ == "__main__":
    main()
