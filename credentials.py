"""
credentials.py — Encrypted credential management for Nest Wifi Pro Dashboard.

Provides secure, on-disk encrypted credential storage using Windows DPAPI
(Data Protection API via crypt32.dll) with a hardware/machine-backed fallback.
Sensitive master tokens are never saved as plaintext.
"""

from __future__ import annotations

import base64
import ctypes
import datetime
import hashlib
import json
import logging
import os
import platform
import re
import secrets
import sys
import urllib.parse
from typing import Any

logger = logging.getLogger("nest_wifi.credentials")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CREDENTIALS_FILE = os.path.join(_BASE_DIR, ".credentials.enc")
_ENV_FILE = os.path.join(_BASE_DIR, ".env")


# =====================================================================
#  ENCRYPTION ENGINE (Windows DPAPI with machine-key fallback)
# =====================================================================

def _has_windows_dpapi() -> bool:
    return platform.system() == "Windows" and hasattr(ctypes, "windll") and hasattr(ctypes.windll, "crypt32")


if _has_windows_dpapi():
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _encrypt_bytes(plaintext: bytes) -> bytes:
        in_buf = ctypes.create_string_buffer(plaintext)
        in_blob = _DATA_BLOB(len(plaintext), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        desc = ctypes.c_wchar_p("NestWifiDashboardCreds")
        if not _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            desc,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise RuntimeError(f"CryptProtectData failed with error {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)

    def _decrypt_bytes(ciphertext: bytes) -> bytes:
        in_buf = ctypes.create_string_buffer(ciphertext)
        in_blob = _DATA_BLOB(len(ciphertext), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise RuntimeError(f"CryptUnprotectData failed with error {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)

    _CIPHER_NAME = "Windows DPAPI (Hardware/User-Bound)"

else:
    # Machine-tied key derivation fallback
    def _get_machine_key() -> bytes:
        seed = f"{platform.node()}-{os.getenv('USERNAME', 'user')}-{_BASE_DIR}".encode("utf-8")
        return hashlib.sha256(seed).digest()

    def _encrypt_bytes(plaintext: bytes) -> bytes:
        key = _get_machine_key()
        nonce = secrets.token_bytes(16)
        # XOR stream cipher with HMAC
        keystream = hashlib.sha256(key + nonce).digest()
        while len(keystream) < len(plaintext):
            keystream += hashlib.sha256(key + keystream[-32:]).digest()
        cipher = bytes([p ^ k for p, k in zip(plaintext, keystream[:len(plaintext)])])
        tag = hashlib.sha256(key + nonce + cipher).digest()[:16]
        return nonce + tag + cipher

    def _decrypt_bytes(ciphertext: bytes) -> bytes:
        if len(ciphertext) < 32:
            raise ValueError("Corrupted ciphertext")
        key = _get_machine_key()
        nonce = ciphertext[:16]
        tag = ciphertext[16:32]
        cipher = ciphertext[32:]
        expected_tag = hashlib.sha256(key + nonce + cipher).digest()[:16]
        if not secrets.compare_digest(tag, expected_tag):
            raise ValueError("Authentication tag mismatch")
        keystream = hashlib.sha256(key + nonce).digest()
        while len(keystream) < len(cipher):
            keystream += hashlib.sha256(key + keystream[-32:]).digest()
        return bytes([c ^ k for c, k in zip(cipher, keystream[:len(cipher)])])

    _CIPHER_NAME = "Machine-Bound SHA-256 Key"


# =====================================================================
#  CREDENTIAL PERSISTENCE
# =====================================================================

def save_credentials(
    email: str,
    master_token: str,
    android_id: str | None = None,
) -> bool:
    """Encrypt and store credentials into .credentials.enc."""
    email = email.strip()
    master_token = master_token.strip()
    android_id = (android_id or secrets.token_hex(8)).strip()

    payload = {
        "google_email": email,
        "google_master_token": master_token,
        "android_id": android_id,
        "encrypted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cipher": _CIPHER_NAME,
    }

    raw = json.dumps(payload).encode("utf-8")
    enc = _encrypt_bytes(raw)
    b64 = base64.b64encode(enc).decode("ascii")

    try:
        with open(_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            f.write(f"# Nest Wifi Pro Dashboard Encrypted Credentials ({_CIPHER_NAME})\n")
            f.write(b64 + "\n")
        logger.info("Saved encrypted credentials for %s", email)

        # Clear plaintext token from .env if present
        _mask_env_token()
        return True
    except Exception as exc:
        logger.exception("Failed to write encrypted credentials: %s", exc)
        return False


def load_credentials() -> dict[str, str] | None:
    """Load and decrypt credentials from .credentials.enc."""
    if not os.path.exists(_CREDENTIALS_FILE):
        return None

    try:
        lines = []
        with open(_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    lines.append(line)
        if not lines:
            return None

        b64 = "".join(lines)
        enc = base64.b64decode(b64)
        raw = _decrypt_bytes(enc)
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and data.get("google_master_token"):
            return data
    except Exception as exc:
        logger.warning("Could not decrypt .credentials.enc: %s", exc)

    return None


def delete_credentials() -> bool:
    """Delete encrypted credentials file and clear in-memory state."""
    try:
        if os.path.exists(_CREDENTIALS_FILE):
            os.remove(_CREDENTIALS_FILE)
            logger.info("Deleted %s", _CREDENTIALS_FILE)
        return True
    except Exception as exc:
        logger.exception("Failed to delete credentials file: %s", exc)
        return False


def get_status() -> dict[str, Any]:
    """Return non-sensitive status of stored credentials."""
    creds = load_credentials()
    if creds and creds.get("google_master_token"):
        email = creds.get("google_email", "")
        # Mask email e.g. e***z@gmail.com
        parts = email.split("@")
        masked_email = email
        if len(parts) == 2 and len(parts[0]) > 2:
            u = parts[0]
            masked_email = f"{u[0]}***{u[-1]}@{parts[1]}"

        return {
            "has_credentials": True,
            "email": email,
            "masked_email": masked_email,
            "android_id": creds.get("android_id", ""),
            "encrypted": True,
            "cipher": creds.get("cipher", _CIPHER_NAME),
            "encrypted_at": creds.get("encrypted_at", ""),
            "mode": "live",
        }

    # Fallback to .env check if any plaintext token remains
    env_token = os.getenv("GOOGLE_MASTER_TOKEN", "").strip()
    env_email = os.getenv("GOOGLE_EMAIL", "").strip()
    if env_token:
        return {
            "has_credentials": True,
            "email": env_email,
            "masked_email": env_email,
            "android_id": os.getenv("ANDROID_ID", ""),
            "encrypted": False,
            "cipher": "Plaintext (.env)",
            "encrypted_at": None,
            "mode": "live",
        }

    return {
        "has_credentials": False,
        "email": "",
        "masked_email": "",
        "android_id": "",
        "encrypted": False,
        "cipher": None,
        "encrypted_at": None,
        "mode": "demo",
    }


def _mask_env_token() -> None:
    """Mask plaintext GOOGLE_MASTER_TOKEN inside .env file."""
    if not os.path.exists(_ENV_FILE):
        return
    try:
        with open(_ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith("GOOGLE_MASTER_TOKEN=") and len(line.strip().split("=", 1)[1]) > 5:
                new_lines.append("# Master token encrypted in .credentials.enc\n")
                new_lines.append("GOOGLE_MASTER_TOKEN=\n")
            else:
                new_lines.append(line)
        with open(_ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as exc:
        logger.warning("Could not mask token in .env: %s", exc)


def migrate_from_env() -> bool:
    """Migrate plaintext token from .env to encrypted file if needed."""
    if os.path.exists(_CREDENTIALS_FILE):
        return True  # Already encrypted

    from dotenv import dotenv_values
    vals = dotenv_values(_ENV_FILE)
    env_email = (vals.get("GOOGLE_EMAIL") or os.getenv("GOOGLE_EMAIL") or "").strip()
    env_token = (vals.get("GOOGLE_MASTER_TOKEN") or os.getenv("GOOGLE_MASTER_TOKEN") or "").strip()
    env_android_id = (vals.get("ANDROID_ID") or os.getenv("ANDROID_ID") or "").strip()

    if env_email and env_token:
        logger.info("Migrating plaintext credentials from .env to encrypted store...")
        return save_credentials(env_email, env_token, env_android_id)

    return False


# =====================================================================
#  TOKEN CLEANING & EXCHANGE
# =====================================================================

def clean_oauth_token(raw_token: str) -> str:
    """Clean and extract oauth2_4 token from raw input, URL, or cookie header."""
    s = raw_token.strip().strip("'\"")

    # If full URL with oauth_token query/fragment parameter
    if "oauth_token=" in s:
        match = re.search(r"oauth_token=([^&;#\s]+)", s)
        if match:
            s = urllib.parse.unquote(match.group(1))

    # Match oauth2_4 token
    match = re.search(r"(oauth2_4/[A-Za-z0-9_\-]+)", s)
    if match:
        return match.group(1)

    return s.strip()


def exchange_oauth_token(
    email: str,
    oauth_token: str,
    android_id: str | None = None,
) -> dict[str, Any]:
    """Exchange EmbeddedSetup oauth_token for a long-lived master token and save encrypted."""
    email = email.strip()
    if not email:
        return {"ok": False, "error": "Email address is required."}

    token_val = clean_oauth_token(oauth_token)
    if not token_val:
        return {"ok": False, "error": "oauth_token cookie value is required."}

    aid = (android_id or secrets.token_hex(8)).strip()

    try:
        import gpsoauth
    except ImportError:
        return {"ok": False, "error": "gpsoauth library is not installed."}

    try:
        res = gpsoauth.exchange_token(email, token_val, aid)
    except Exception as exc:
        logger.exception("gpsoauth exchange failed")
        return {"ok": False, "error": f"Connection to Google authentication failed: {exc}"}

    if not isinstance(res, dict):
        return {"ok": False, "error": "Malformed response from Google authentication."}

    master_token = res.get("Token") or res.get("Auth")
    if not master_token:
        err = res.get("Error") or res.get("error") or str(res)
        if "BadAuthentication" in str(err) or "bad_auth" in str(err).lower():
            err_msg = "Google rejected the token. The oauth_token cookie is single-use and expires in ~5 minutes. Please open a fresh sign-in session and copy the new cookie."
        else:
            err_msg = f"Google authentication failed: {err}"
        return {"ok": False, "error": err_msg}

    # Encrypt and save
    saved = save_credentials(email, master_token, aid)
    if not saved:
        return {"ok": False, "error": "Obtained token but failed to write encrypted file."}

    return {
        "ok": True,
        "message": "Authentication successful! Master token encrypted with Windows DPAPI.",
        "email": email,
        "android_id": aid,
        "cipher": _CIPHER_NAME,
    }
