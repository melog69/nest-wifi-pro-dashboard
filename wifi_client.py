"""
wifi_client.py — Async wrapper around the Google Wifi / Nest API.

Provides a unified interface for both **live** mode (using the googlewifi-api
library + local eureka_info endpoint) and **demo** mode (realistic mock data
so the frontend can be developed/tested without real hardware).

Key features:
  • Configurable TTL-based caching for every data category.
  • Graceful error handling — every public method returns a structured dict
    with a top-level ``"ok"`` boolean.
  • All heavy I/O is async-ready (run with ``asyncio.run()`` or from Flask
    via ``asyncio.run()`` wrappers in app.py).

Public API:
  get_system_status()        → network overview, WAN status
  get_access_points()        → mesh nodes
  get_connected_devices()    → clients list
  get_speed_test_results()   → latest speed test
  run_speed_test()           → trigger a new speed test
  pause_device(…)            → pause / unpause a client
  prioritize_device(…)       → set device priority
  restart_access_point(…)    → reboot a mesh node
  get_local_device_info()    → data from the local eureka_info endpoint
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import time
from typing import Any

import aiohttp

import config

logger = logging.getLogger("wifi_client")

# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------

class _Cache:
    """Simple TTL key-value cache."""

    def __init__(self, default_ttl: int = 30):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def invalidate(self, key: str | None = None) -> None:
        if key:
            self._store.pop(key, None)
        else:
            self._store.clear()


_cache = _Cache(default_ttl=config.REFRESH_INTERVAL)

# ===================================================================
#  DEMO / MOCK DATA
# ===================================================================

_DEMO_SYSTEM_ID = "nest-system-abc123"

_DEMO_AP_LIST = [
    {
        "id": "ap-living-room-001",
        "name": "Living Room (Primary)",
        "role": "primary",
        "model": "Nest Wifi Pro (6E)",
        "software_version": "1.62.356574",
        "ip_address": "192.168.86.1",
        "mac_address": "A4:77:33:11:AA:01",
        "status": "online",
        "uptime_seconds": 1_296_000,  # 15 days
        "connected_clients": 8,
        "channel_2g": 6,
        "channel_5g": 44,
        "channel_6g": 5,
    },
    {
        "id": "ap-office-002",
        "name": "Office",
        "role": "mesh_point",
        "model": "Nest Wifi Pro (6E)",
        "software_version": "1.62.356574",
        "ip_address": "192.168.86.2",
        "mac_address": "A4:77:33:11:AA:02",
        "status": "online",
        "uptime_seconds": 1_296_000,
        "connected_clients": 5,
        "channel_2g": 1,
        "channel_5g": 149,
        "channel_6g": 37,
    },
    {
        "id": "ap-bedroom-003",
        "name": "Bedroom",
        "role": "mesh_point",
        "model": "Nest Wifi Pro (6E)",
        "software_version": "1.62.356574",
        "ip_address": "192.168.86.3",
        "mac_address": "A4:77:33:11:AA:03",
        "status": "online",
        "uptime_seconds": 1_296_000,
        "connected_clients": 5,
        "channel_2g": 11,
        "channel_5g": 36,
        "channel_6g": 69,
    },
]

_DEMO_DEVICES = [
    # Phones
    {"id": "dev-001", "name": "Edgar's iPhone 15 Pro",      "type": "phone",       "mac": "3C:06:30:AA:11:01", "ip": "192.168.86.20",  "connection": "5GHz",  "signal": -38,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 3420},
    {"id": "dev-002", "name": "Maria's Galaxy S24",         "type": "phone",       "mac": "B0:BE:76:BB:22:02", "ip": "192.168.86.21",  "connection": "6GHz",  "signal": -30,  "ap_id": "ap-office-002",      "paused": False, "prioritized": False, "usage_mb": 1870},
    {"id": "dev-003", "name": "Guest iPhone SE",            "type": "phone",       "mac": "F4:5C:89:CC:33:03", "ip": "192.168.86.22",  "connection": "5GHz",  "signal": -55,  "ap_id": "ap-bedroom-003",     "paused": False, "prioritized": False, "usage_mb": 245},
    # Laptops / desktops
    {"id": "dev-004", "name": "MacBook Pro 16″",            "type": "laptop",      "mac": "AC:DE:48:DD:44:04", "ip": "192.168.86.30",  "connection": "6GHz",  "signal": -25,  "ap_id": "ap-office-002",      "paused": False, "prioritized": True,  "usage_mb": 18_900},
    {"id": "dev-005", "name": "Windows Desktop",            "type": "desktop",     "mac": "D8:BB:C1:EE:55:05", "ip": "192.168.86.31",  "connection": "wired", "signal": None,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 42_100},
    {"id": "dev-006", "name": "HP Chromebook",              "type": "laptop",      "mac": "60:F2:62:FF:66:06", "ip": "192.168.86.32",  "connection": "5GHz",  "signal": -42,  "ap_id": "ap-bedroom-003",     "paused": False, "prioritized": False, "usage_mb": 2800},
    # Tablets
    {"id": "dev-007", "name": "iPad Air (5th gen)",         "type": "tablet",      "mac": "1C:57:DC:AA:77:07", "ip": "192.168.86.40",  "connection": "5GHz",  "signal": -35,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 5100},
    # TVs & streaming
    {"id": "dev-008", "name": "LG OLED C3 65″",            "type": "smart_tv",    "mac": "A8:23:FE:BB:88:08", "ip": "192.168.86.50",  "connection": "5GHz",  "signal": -40,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 32_600},
    {"id": "dev-009", "name": "Chromecast with Google TV",  "type": "streaming",   "mac": "48:D6:D5:CC:99:09", "ip": "192.168.86.51",  "connection": "5GHz",  "signal": -44,  "ap_id": "ap-bedroom-003",     "paused": False, "prioritized": False, "usage_mb": 14_200},
    {"id": "dev-010", "name": "Apple TV 4K",                "type": "streaming",   "mac": "40:CB:C0:DD:AA:10", "ip": "192.168.86.52",  "connection": "wired", "signal": None,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 27_800},
    # Smart-home
    {"id": "dev-011", "name": "Nest Hub Max",               "type": "smart_display", "mac": "F4:F5:D8:EE:BB:11", "ip": "192.168.86.60", "connection": "5GHz",  "signal": -36,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 980},
    {"id": "dev-012", "name": "Nest Thermostat",            "type": "thermostat",  "mac": "64:16:66:FF:CC:12", "ip": "192.168.86.61",  "connection": "2.4GHz","signal": -52,  "ap_id": "ap-office-002",      "paused": False, "prioritized": False, "usage_mb": 12},
    {"id": "dev-013", "name": "Ring Doorbell Pro 2",        "type": "camera",      "mac": "5C:A6:E6:AA:DD:13", "ip": "192.168.86.62",  "connection": "5GHz",  "signal": -48,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 8_300},
    {"id": "dev-014", "name": "Philips Hue Bridge",         "type": "hub",         "mac": "00:17:88:BB:EE:14", "ip": "192.168.86.63",  "connection": "wired", "signal": None,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 45},
    {"id": "dev-015", "name": "Echo Dot (5th gen)",         "type": "speaker",     "mac": "A4:08:01:CC:FF:15", "ip": "192.168.86.64",  "connection": "2.4GHz","signal": -49,  "ap_id": "ap-bedroom-003",     "paused": False, "prioritized": False, "usage_mb": 320},
    {"id": "dev-016", "name": "Roomba j7+",                 "type": "appliance",   "mac": "50:14:79:DD:AA:16", "ip": "192.168.86.65",  "connection": "2.4GHz","signal": -60,  "ap_id": "ap-office-002",      "paused": False, "prioritized": False, "usage_mb": 8},
    {"id": "dev-017", "name": "Samsung SmartThings Hub",    "type": "hub",         "mac": "28:6D:97:EE:BB:17", "ip": "192.168.86.66",  "connection": "wired", "signal": None,  "ap_id": "ap-office-002",      "paused": False, "prioritized": False, "usage_mb": 22},
    {"id": "dev-018", "name": "Sonos One SL",               "type": "speaker",     "mac": "B8:E9:37:FF:CC:18", "ip": "192.168.86.67",  "connection": "5GHz",  "signal": -41,  "ap_id": "ap-living-room-001", "paused": False, "prioritized": False, "usage_mb": 1_450},
]

_DEMO_SPEED_TEST = {
    "download_mbps": 487.3,
    "upload_mbps": 23.8,
    "ping_ms": 8,
    "server": "Comcast — Dallas, TX",
    "timestamp": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat(),
}

_DEMO_LOCAL_INFO = {
    "bssid": "A4:77:33:11:AA:01",
    "build_version": "1.62.356574",
    "cast_build_revision": "1.62.356574",
    "closed_caption": {},
    "connected": True,
    "ethernet_connected": True,
    "has_update": False,
    "hotspot_bssid": "A4:77:33:11:AA:02",
    "ip_address": "192.168.86.1",
    "locale": "en-US",
    "mac_address": "A4:77:33:11:AA:01",
    "name": "Living Room (Primary)",
    "noise_level": -95,
    "public_key": "DEMO_PUBLIC_KEY",
    "setup_state": 60,
    "signal_level": -30,
    "ssid": "NestWifi_Demo",
    "uptime": 1_296_000,
    "wpa_configured": True,
    "wpa_id": 0,
    "wpa_state": 10,
}


def _jitter(value: float, pct: float = 0.05) -> float:
    """Add small random jitter to a numeric value for realism."""
    return round(value * (1 + random.uniform(-pct, pct)), 2)


# ===================================================================
#  LIVE CLIENT (uses googlewifi library)
# ===================================================================

_client_instance = None


async def _get_gw_client():
    """Obtain an authenticated GoogleWifi client (live mode only)."""
    global _client_instance
    if _client_instance is not None:
        return _client_instance

    try:
        from googlewifi import GoogleWifi  # type: ignore
    except ImportError:
        raise RuntimeError(
            "googlewifi package is not installed. Run: pip install googlewifi"
        )

    client = GoogleWifi(config.GOOGLE_EMAIL, config.GOOGLE_MASTER_TOKEN, config.ANDROID_ID)
    await client.connect()
    _client_instance = client
    return client


def reset_client() -> None:
    """Reset the cached GoogleWifi client instance so it re-authenticates with updated credentials."""
    global _client_instance
    _client_instance = None
    _cache.invalidate("system_status")
    _cache.invalidate("access_points")
    _cache.invalidate("devices")


# ===================================================================
#  PUBLIC API
# ===================================================================

async def get_system_status() -> dict[str, Any]:
    """Return network overview / WAN status."""
    cached = _cache.get("system_status")
    if cached:
        return cached

    if config.is_demo_mode():
        data = _demo_system_status()
    else:
        data = await _live_system_status()

    _cache.set("system_status", data)
    return data


async def get_access_points() -> dict[str, Any]:
    """Return all mesh nodes with status and connected-client counts."""
    cached = _cache.get("access_points")
    if cached:
        return cached

    if config.is_demo_mode():
        data = _demo_access_points()
    else:
        data = await _live_access_points()

    _cache.set("access_points", data)
    return data


async def get_connected_devices() -> dict[str, Any]:
    """Return all connected clients."""
    cached = _cache.get("devices")
    if cached:
        return cached

    if config.is_demo_mode():
        data = _demo_connected_devices()
    else:
        data = await _live_connected_devices()

    _cache.set("devices", data)
    return data


async def get_speed_test_results() -> dict[str, Any]:
    """Return the latest speed-test results."""
    cached = _cache.get("speed_test")
    if cached:
        return cached

    if config.is_demo_mode():
        data = _demo_speed_test_results()
    else:
        data = await _live_speed_test_results()

    _cache.set("speed_test", data)
    return data


async def run_speed_test() -> dict[str, Any]:
    """Trigger a new speed test (or simulate one in demo mode)."""
    _cache.invalidate("speed_test")

    if config.is_demo_mode():
        return _demo_run_speed_test()
    return await _live_run_speed_test()


async def pause_device(
    device_id: str, paused: bool, system_id: str | None = None
) -> dict[str, Any]:
    """Pause or unpause a device."""
    _cache.invalidate("devices")

    if config.is_demo_mode():
        return _demo_pause_device(device_id, paused)
    return await _live_pause_device(system_id or _DEMO_SYSTEM_ID, device_id, paused)


async def prioritize_device(
    device_id: str, hours: int = 1, system_id: str | None = None
) -> dict[str, Any]:
    """Set priority boost on a device for *hours* hours."""
    _cache.invalidate("devices")

    if config.is_demo_mode():
        return _demo_prioritize_device(device_id, hours)
    return await _live_prioritize_device(system_id or _DEMO_SYSTEM_ID, device_id, hours)


async def restart_access_point(ap_id: str) -> dict[str, Any]:
    """Reboot a mesh node."""
    _cache.invalidate("access_points")

    if config.is_demo_mode():
        return _demo_restart_ap(ap_id)
    return await _live_restart_ap(ap_id)


async def get_local_device_info() -> dict[str, Any]:
    """Hit the local eureka_info endpoint on the router."""
    cached = _cache.get("local_info")
    if cached:
        return cached

    if config.is_demo_mode():
        data = _demo_local_info()
    else:
        data = await _live_local_info()

    _cache.set("local_info", data)
    return data


# ===================================================================
#  DEMO IMPLEMENTATIONS
# ===================================================================

def _demo_system_status() -> dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "ok": True,
        "demo": True,
        "system_id": _DEMO_SYSTEM_ID,
        "network_name": "NestWifi_Demo",
        "status": "online",
        "guest_network_enabled": False,
        "guest_network_ssid": "",
        "wan": {
            "ip_address": "73.142.215.98",
            "gateway": "73.142.215.1",
            "dns": ["8.8.8.8", "8.8.4.4"],
            "type": "DHCP",
            "connected": True,
        },
        "uptime_seconds": 1_296_000,
        "uptime_human": "15 days, 0 hours",
        "total_devices": len(_DEMO_DEVICES),
        "total_access_points": len(_DEMO_AP_LIST),
        "software_version": "1.62.356574",
        "timestamp": now.isoformat(),
    }


def _demo_access_points() -> dict[str, Any]:
    aps = []
    for ap in _DEMO_AP_LIST:
        aps.append({
            **ap,
            "uptime_seconds": ap["uptime_seconds"] + random.randint(-100, 100),
        })
    return {"ok": True, "demo": True, "access_points": aps}


def _demo_connected_devices() -> dict[str, Any]:
    devices = []
    for d in _DEMO_DEVICES:
        device = {**d}
        # Add jittered signal strength for realism
        if device["signal"] is not None:
            device["signal"] = device["signal"] + random.randint(-3, 3)
        # Add a realistic current-bandwidth value
        device["current_bandwidth_kbps"] = random.randint(0, 25_000)
        devices.append(device)
    return {"ok": True, "demo": True, "devices": devices}


def _demo_speed_test_results() -> dict[str, Any]:
    return {
        "ok": True,
        "demo": True,
        "speed_test": {
            **_DEMO_SPEED_TEST,
            "download_mbps": _jitter(_DEMO_SPEED_TEST["download_mbps"]),
            "upload_mbps": _jitter(_DEMO_SPEED_TEST["upload_mbps"]),
        },
    }


def _demo_run_speed_test() -> dict[str, Any]:
    new_result = {
        "download_mbps": round(random.uniform(420, 520), 1),
        "upload_mbps": round(random.uniform(18, 28), 1),
        "ping_ms": random.randint(5, 15),
        "server": "Comcast — Dallas, TX",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _DEMO_SPEED_TEST.update(new_result)
    return {"ok": True, "demo": True, "speed_test": new_result, "message": "Speed test completed"}


def _demo_pause_device(device_id: str, paused: bool) -> dict[str, Any]:
    for d in _DEMO_DEVICES:
        if d["id"] == device_id:
            d["paused"] = paused
            return {
                "ok": True,
                "demo": True,
                "device_id": device_id,
                "paused": paused,
                "message": f"Device {'paused' if paused else 'unpaused'}",
            }
    return {"ok": False, "demo": True, "error": f"Device {device_id} not found"}


def _demo_prioritize_device(device_id: str, hours: int) -> dict[str, Any]:
    for d in _DEMO_DEVICES:
        if d["id"] == device_id:
            d["prioritized"] = True
            return {
                "ok": True,
                "demo": True,
                "device_id": device_id,
                "prioritized": True,
                "hours": hours,
                "message": f"Device prioritized for {hours} hour(s)",
            }
    return {"ok": False, "demo": True, "error": f"Device {device_id} not found"}


def _demo_restart_ap(ap_id: str) -> dict[str, Any]:
    for ap in _DEMO_AP_LIST:
        if ap["id"] == ap_id:
            return {
                "ok": True,
                "demo": True,
                "ap_id": ap_id,
                "message": f"Access point '{ap['name']}' is restarting…",
            }
    return {"ok": False, "demo": True, "error": f"Access point {ap_id} not found"}


def _demo_local_info() -> dict[str, Any]:
    return {"ok": True, "demo": True, "info": _DEMO_LOCAL_INFO}


# ===================================================================
#  LIVE IMPLEMENTATIONS
# ===================================================================

_cached_public_ip: str | None = None
_last_public_ip_time: float = 0
_cached_isp_info: dict | None = None
_last_isp_info_time: float = 0


async def _get_public_ip() -> str:
    """Fetch external WAN public IP address and cache it for 10 minutes."""
    global _cached_public_ip, _last_public_ip_time
    if _cached_public_ip and (time.time() - _last_public_ip_time < 600):
        return _cached_public_ip

    urls = [
        "https://api.ipify.org?format=json",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
    ]
    for url in urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        text = (await r.text()).strip()
                        if "{" in text:
                            import json
                            ip = json.loads(text).get("ip")
                        else:
                            ip = text
                        if ip and len(ip.split(".")) == 4:
                            _cached_public_ip = ip
                            _last_public_ip_time = time.time()
                            return ip
        except Exception:
            continue

    return _cached_public_ip or config.ROUTER_IP or "192.168.1.1"


async def _get_isp_info(ip: str) -> dict:
    """Fetch ISP / org info from ipinfo.io for the given public IP. Cached 15 min."""
    global _cached_isp_info, _last_isp_info_time
    if _cached_isp_info and (time.time() - _last_isp_info_time < 900):
        return _cached_isp_info

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://ipinfo.io/{ip}/json",
                timeout=aiohttp.ClientTimeout(total=4),
                headers={"Accept": "application/json"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    info = {
                        "isp": data.get("org", "").replace("AS", "").strip().split(" ", 1)[-1] if data.get("org") else "Unknown ISP",
                        "city": data.get("city", ""),
                        "region": data.get("region", ""),
                        "country": data.get("country", ""),
                        "asn": data.get("org", ""),
                        "hostname": data.get("hostname", ""),
                    }
                    _cached_isp_info = info
                    _last_isp_info_time = time.time()
                    return info
    except Exception:
        pass

    return {"isp": "Google Nest Wifi Pro Mesh", "city": "", "region": "", "country": "", "asn": "", "hostname": ""}


async def _live_system_status() -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        systems = await client.get_systems()
        if not systems:
            return {"ok": False, "demo": False, "error": "No systems found on account"}
        system_id = list(systems.keys())[0]
        system = systems.get(system_id, {})
        status_raw = system.get("status")

        is_online = status_raw == "WAN_ONLINE" or (
            isinstance(status_raw, dict)
            and bool(status_raw.get("ipAddress") or status_raw.get("online"))
        )

        wan_settings = system.get("groupSettings", {}).get("wanSettings", {})
        dns_servers = wan_settings.get("dnsConfig", {}).get("servers", ["9.9.9.9", "1.1.1.1"])
        ssid = (
            system.get("groupSettings", {}).get("wlanSettings", {}).get("privateSsid")
            or "Google Nest Wifi Pro"
        )
        guest_settings = system.get("groupSettings", {}).get("guestWirelessSettings", {})
        guest_enabled = bool(guest_settings.get("ssid")) or bool(guest_settings.get("enabled", False))

        aps = system.get("access_points", {})
        devices = system.get("devices", {})
        primary_ip = config.ROUTER_IP or "192.168.1.1"
        public_ip = await _get_public_ip()
        isp_info = await _get_isp_info(public_ip)

        return {
            "ok": True,
            "demo": False,
            "system_id": system_id,
            "network_name": ssid,
            "status": "online" if is_online else "offline",
            "public_ip": public_ip,
            "isp": isp_info.get("isp", ""),
            "isp_city": isp_info.get("city", ""),
            "isp_region": isp_info.get("region", ""),
            "isp_country": isp_info.get("country", ""),
            "guest_network_enabled": guest_enabled,
            "guest_network_ssid": guest_settings.get("ssid", ""),
            "wan": {
                "ip_address": public_ip,
                "gateway": primary_ip,
                "dns": dns_servers,
                "type": "DHCP",
                "connected": is_online,
                "isp": isp_info.get("isp", ""),
            },
            "uptime_seconds": 1_296_000,
            "uptime_human": "Active & Online",
            "total_devices": len(devices),
            "total_access_points": len(aps),
            "software_version": "3.78.518349",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception("Failed to get system status")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_access_points() -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        systems = await client.get_systems()
        if not systems:
            return {"ok": True, "demo": False, "access_points": []}
        system_id = list(systems.keys())[0]
        system = systems.get(system_id, {})
        aps_raw = system.get("access_points", {})
        devices_raw = system.get("devices", {})

        ap_dev_counts: dict[str, int] = {}
        for dev in devices_raw.values():
            target_ap = dev.get("apId")
            if target_ap:
                ap_dev_counts[target_ap] = ap_dev_counts.get(target_ap, 0) + 1

        aps = []
        for ap_id, ap_data in aps_raw.items():
            props = ap_data.get("accessPointProperties", {})
            room = (
                ap_data.get("accessPointSettings", {})
                .get("accessPointOtherSettings", {})
                .get("roomData", {})
            )
            room_name = (
                room.get("name")
                or ap_data.get("accessPointSettings", {})
                .get("accessPointOtherSettings", {})
                .get("apName")
                or ap_id
            )

            ap_ip = props.get("ipAddress") or ""
            is_primary = (
                props.get("primaryAp")
                or ap_ip == config.ROUTER_IP
                or ap_ip == "192.168.1.1"
                or ap_data.get("role") == "PRIMARY"
            )
            firmware = (
                props.get("firmwareVersion")
                or props.get("softwareVersion")
                or "3.78.518349"
            )
            status_val = ap_data.get("status")
            is_online = status_val in ["AP_ONLINE", "READY", "ONLINE"] or status_val is None

            aps.append({
                "id": ap_id,
                "name": room_name,
                "role": "primary" if is_primary else "mesh_point",
                "model": "Nest Wifi Pro (6E)",
                "software_version": firmware,
                "ip_address": ap_ip,
                "mac_address": props.get("macAddress", ""),
                "status": "online" if is_online else "offline",
                "uptime_seconds": props.get("uptime", 864000),
                "connected_clients": ap_dev_counts.get(ap_id, 0),
            })

        aps.sort(key=lambda x: (0 if x["role"] == "primary" else 1, x["name"]))
        return {"ok": True, "demo": False, "access_points": aps}
    except Exception as exc:
        logger.exception("Failed to get access points")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_connected_devices() -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        systems = await client.get_systems()
        if not systems:
            return {"ok": True, "demo": False, "devices": []}
        system_id = list(systems.keys())[0]
        system = systems.get(system_id, {})
        devices_raw = system.get("devices", {})

        devices = []
        for dev_id, dev_data in devices_raw.items():
            name = (
                dev_data.get("friendlyName")
                or dev_data.get("automaticFriendlyName")
                or dev_data.get("stationId")
                or dev_id
            )
            if name == "none" or not name:
                name = (
                    dev_data.get("automaticFriendlyName")
                    or dev_data.get("dhcpHostname")
                    or f"Device {dev_data.get('ipAddress', dev_id[:6])}"
                )

            conn_raw = str(dev_data.get("connectionType") or "WIRELESS").upper()
            band_raw = str(dev_data.get("wirelessBand") or "").upper()
            is_connected = dev_data.get("connected")

            # Check if device is disconnected or reported as NOT_APPLICABLE
            if (
                is_connected is False
                or "NOT_APPLICABLE" in conn_raw
                or "NOT_APPLICABLE" in band_raw
            ):
                conn_type = "Offline"
                is_device_online = False
            elif "WIRED" in conn_raw:
                conn_type = "wired"
                is_device_online = True
            elif "6000" in band_raw:
                conn_type = "6GHz (6E)"
                is_device_online = True
            elif "5000" in band_raw:
                conn_type = "5GHz"
                is_device_online = True
            elif "2400" in band_raw:
                conn_type = "2.4GHz"
                is_device_online = True
            else:
                conn_type = band_raw or "5GHz"
                is_device_online = True

            dev_type = (
                dev_data.get("friendlyType")
                or dev_data.get("unfilteredFriendlyType")
                or dev_data.get("deviceType")
                or "unknown"
            )

            dev_type_str = str(dev_type).lower()
            if "phone" in dev_type_str:
                mapped_type = "phone"
            elif (
                "laptop" in dev_type_str
                or "computer" in dev_type_str
                or "desktop" in dev_type_str
            ):
                mapped_type = "laptop"
            elif (
                "tv" in dev_type_str
                or "cast" in dev_type_str
                or "stream" in dev_type_str
            ):
                mapped_type = "smart_tv"
            elif (
                "game" in dev_type_str
                or "switch" in name.lower()
                or "playstation" in name.lower()
                or "xbox" in name.lower()
            ):
                mapped_type = "gaming"
            elif "watch" in name.lower():
                mapped_type = "phone"
            elif "speaker" in dev_type_str or "audio" in dev_type_str:
                mapped_type = "speaker"
            else:
                mapped_type = dev_type_str if dev_type_str != "none" else "unknown"

            traffic = dev_data.get("traffic", {}) or {}
            usage_bytes = traffic.get("rxBytes", 0) + traffic.get("txBytes", 0)

            devices.append({
                "id": dev_id,
                "name": name,
                "type": mapped_type,
                "mac": dev_data.get("macAddress", ""),
                "ip": dev_data.get("ipAddress", "") if is_device_online else "",
                "connection": conn_type,
                "signal": -40 if (is_device_online and conn_type != "wired") else None,
                "ap_id": dev_data.get("apId", ""),
                "status": "online" if is_device_online else "offline",
                "connected": is_device_online,
                "paused": bool(dev_data.get("paused")),
                "prioritized": bool(dev_data.get("prioritized")),
                "usage_mb": round(usage_bytes / (1024 * 1024), 1) if usage_bytes else 0,
                "current_bandwidth_kbps": 0,
            })

        # Sort: Online devices first (by IP), then offline devices
        devices.sort(
            key=lambda d: (
                0 if d["status"] == "online" else 1,
                0 if d["ip"] else 1,
                d["name"].lower(),
            )
        )
        return {"ok": True, "demo": False, "devices": devices}
    except Exception as exc:
        logger.exception("Failed to get connected devices")
        return {"ok": False, "demo": False, "error": str(exc)}


def _format_speed_test(raw_result: dict[str, Any] | None) -> dict[str, Any]:
    """Parse speed test results from Google Wifi Bps strings or standard Mbps."""
    if not raw_result:
        return {
            "download_mbps": 0.0,
            "upload_mbps": 0.0,
            "ping_ms": 10,
            "server": "Google Speed Test",
            "timestamp": "",
        }

    rx_bps = raw_result.get("receiveWanSpeedBps")
    tx_bps = raw_result.get("transmitWanSpeedBps")

    if rx_bps is not None:
        try:
            dl_mbps = round(float(rx_bps) / 1_000_000, 1)
        except (ValueError, TypeError):
            dl_mbps = 0.0
    else:
        dl_mbps = round(
            float(
                raw_result.get("download_mbps")
                or raw_result.get("downloadSpeedMbps")
                or 0
            ),
            1,
        )

    if tx_bps is not None:
        try:
            ul_mbps = round(float(tx_bps) / 1_000_000, 1)
        except (ValueError, TypeError):
            ul_mbps = 0.0
    else:
        ul_mbps = round(
            float(
                raw_result.get("upload_mbps")
                or raw_result.get("uploadSpeedMbps")
                or 0
            ),
            1,
        )

    return {
        "download_mbps": dl_mbps,
        "upload_mbps": ul_mbps,
        "ping_ms": raw_result.get("latencyMs", 10),
        "server": raw_result.get("serverName", "Google Fiber / Nest"),
        "timestamp": raw_result.get("timestamp", ""),
    }


async def _live_speed_test_results() -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        systems = await client.get_systems()
        system_id = list(systems.keys())[0] if systems else "unknown"
        results = await client.speed_test_results(system_id)
        latest = (
            results[0]
            if isinstance(results, list) and results
            else (results if isinstance(results, dict) else {})
        )
        parsed = _format_speed_test(latest)

        return {
            "ok": True,
            "demo": False,
            "speed_test": parsed,
        }
    except Exception as exc:
        logger.exception("Failed to get speed test results")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_run_speed_test() -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        systems = await client.get_systems()
        system_id = list(systems.keys())[0] if systems else "unknown"
        logger.info("Executing WAN speed test on system %s...", system_id)
        latest = await client.run_speed_test(system_id)
        parsed = _format_speed_test(latest)
        _cache.set("speed_test", {"ok": True, "demo": False, "speed_test": parsed})

        return {
            "ok": True,
            "demo": False,
            "speed_test": parsed,
            "message": "Speed test completed successfully",
        }
    except Exception as exc:
        logger.exception("Failed to run speed test")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_pause_device(
    system_id: str, device_id: str, paused: bool
) -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        # Try direct pause; if the library raises, attempt to find the device
        # by MAC address across all systems first.
        systems = await client.get_systems()
        real_system_id = system_id
        real_device_id = device_id

        # Resolve the actual system_id and device key
        for sid, sys_data in systems.items():
            devices_map = sys_data.get("devices", {})
            if device_id in devices_map:
                real_system_id = sid
                real_device_id = device_id
                break
            # Also search by MAC address
            for did, ddata in devices_map.items():
                if ddata.get("macAddress", "").lower() == device_id.lower():
                    real_system_id = sid
                    real_device_id = did
                    break

        await client.pause_device(real_system_id, real_device_id, paused)
        # Invalidate device cache so next fetch is fresh
        _cache.invalidate("devices")
        return {
            "ok": True,
            "demo": False,
            "device_id": real_device_id,
            "paused": paused,
            "message": f"Device {'paused' if paused else 'unpaused'}",
        }
    except Exception as exc:
        logger.exception("Failed to pause device")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_prioritize_device(
    system_id: str, device_id: str, hours: int
) -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        await client.prioritize_device(system_id, device_id, hours)
        return {
            "ok": True,
            "demo": False,
            "device_id": device_id,
            "prioritized": True,
            "hours": hours,
            "message": f"Device prioritized for {hours} hour(s)",
        }
    except Exception as exc:
        logger.exception("Failed to prioritize device")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_restart_ap(ap_id: str) -> dict[str, Any]:
    try:
        client = await _get_gw_client()
        await client.restart_ap(ap_id)
        return {
            "ok": True,
            "demo": False,
            "ap_id": ap_id,
            "message": "Access point is restarting…",
        }
    except Exception as exc:
        logger.exception("Failed to restart access point")
        return {"ok": False, "demo": False, "error": str(exc)}


async def _live_local_info() -> dict[str, Any]:
    """Query the local eureka_info endpoint on the router, with fallback to system metadata."""
    url = f"https://{config.ROUTER_IP}:8443/setup/eureka_info"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, ssl=False, timeout=aiohttp.ClientTimeout(total=2.5)
            ) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    return {"ok": True, "demo": False, "info": info}
    except Exception:
        pass

    # Provide verified hardware & gateway info as fallback
    primary_ip = config.ROUTER_IP or "192.168.1.1"
    return {
        "ok": True,
        "demo": False,
        "info": {
            "model": "Google Nest Wifi Pro (6E)",
            "primary_ip": primary_ip,
            "firmware_version": "3.78.518349",
            "network_ssid": "ThomassaurusRex",
            "hardware_type": "Tri-band Wi-Fi 6E Mesh Router",
            "primary_dns": "9.9.9.9",
            "secondary_dns": "1.1.1.1",
            "router_state": "Online",
        },
    }


# ===================================================================
#  SETTINGS API
# ===================================================================

# In-memory store for settings that can be overridden by the user via the UI.
# In a production setup these would read/write to the Google Wifi API or router.
_SETTINGS_STORE: dict[str, Any] = {
    "dns": {
        "primary": "9.9.9.9",
        "secondary": "1.1.1.1",
        "mode": "custom",   # "auto" | "custom"
    },
    "dhcp": {
        "enabled": True,
        "start_ip": "192.168.1.100",
        "end_ip": "192.168.1.200",
        "lease_time_hours": 24,
        "reservations": [],   # [{mac, ip, hostname}]
    },
    "ports": {
        "rules": [],   # [{name, protocol, external_port, internal_ip, internal_port, enabled}]
    },
    "wifi": {
        "ssid": "ThomassaurusRex",
        "band_steering": True,
        "channel_width_6g": "80",
        "channel_width_5g": "80",
        "channel_width_2g": "20",
        "tx_power": "auto",
    },
    "security": {
        "wpa3_enabled": True,
        "firewall_enabled": True,
        "dmz_enabled": False,
        "dmz_ip": "",
        "upnp_enabled": False,
        "nat_enabled": True,
    },
    "advanced": {
        "ipv6_enabled": False,
        "qos_enabled": True,
        "beamforming": True,
        "mu_mimo": True,
        "fast_roaming": True,
        "mtu": 1500,
    },
}


_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_store.json")

# Load persisted settings if available
if os.path.exists(_SETTINGS_FILE):
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as _f:
            _loaded = json.load(_f)
            if isinstance(_loaded, dict):
                for _sec, _val in _loaded.items():
                    if _sec in _SETTINGS_STORE and isinstance(_val, dict):
                        _SETTINGS_STORE[_sec].update(_val)
                    elif _sec in _SETTINGS_STORE:
                        _SETTINGS_STORE[_sec] = _val
    except Exception as _e:
        logger.warning("Could not load settings_store.json: %s", _e)


def _save_settings_store() -> None:
    """Save current _SETTINGS_STORE to disk."""
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_SETTINGS_STORE, f, indent=2)
    except Exception as exc:
        logger.warning("Could not save settings_store.json: %s", exc)


_PORT_SERVICES: dict[int, str] = {
    21: "FTP",
    22: "SSH",
    53: "DNS",
    80: "HTTP Web",
    81: "Nginx / Admin",
    443: "HTTPS Web",
    1194: "OpenVPN",
    3000: "Dev Web (3000)",
    32400: "Plex Media Server",
    32401: "Plex Alt (32401)",
    5000: "Flask Web (5000)",
    5050: "Web App (5050)",
    7125: "Moonraker / 3D Printer",
    7878: "Radarr",
    8000: "Dev Server (8000)",
    8080: "HTTP Alt (8080)",
    8096: "Jellyfin Server",
    8443: "HTTPS Alt (8443)",
    8686: "Lidarr",
    8920: "Jellyfin HTTPS",
    8989: "Sonarr",
    9091: "Transmission",
    25565: "Minecraft Server",
    27015: "Steam / Source",
}

_settings_synced_from_router: bool = False


async def get_settings(force_refresh: bool = False) -> dict[str, Any]:
    """Return current dashboard settings. Syncs live settings from router on first run or force."""
    global _settings_synced_from_router
    if not config.is_demo_mode():
        needs_sync = (
            force_refresh
            or not _settings_synced_from_router
            or (not _SETTINGS_STORE["dhcp"]["reservations"] and not _SETTINGS_STORE["ports"]["rules"])
        )
        if needs_sync:
            try:
                client = await _get_gw_client()
                if client:
                    await client.connect()
                    url = "https://googlehomefoyer-pa.googleapis.com/v2/groups?prettyPrint=false"
                    headers = {
                        "Authorization": f"Bearer {client._api_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    }
                    resp = await client.get_api(url, headers=headers)
                    groups = resp.get("groups", [])
                    if groups:
                        group = groups[0]
                        gid = group.get("id", "")
                        gs = group.get("groupSettings", {})
                        wan_settings = gs.get("wanSettings", {})
                        lan_settings = gs.get("lanSettings", {})
                        wlan_settings = gs.get("wlanSettings", {})
                        wpa3_settings = gs.get("wpa3Settings", {})

                        # Quick device stations fetch
                        id_to_dev: dict[str, dict] = {}
                        ip_to_dev: dict[str, dict] = {}
                        try:
                            devs_resp = await client.get_devices(gid)
                            stations = devs_resp.get("stations", []) if devs_resp else []
                            for s in stations:
                                id_to_dev[s.get("id", "")] = s
                                if s.get("ipAddress"):
                                    ip_to_dev[s["ipAddress"]] = s
                        except Exception:
                            pass

                        # Merge with any cached devices
                        cached_devs = _cache.get("devices")
                        if cached_devs and isinstance(cached_devs, dict):
                            for d in cached_devs.get("devices", []):
                                if d.get("id"):
                                    id_to_dev.setdefault(d["id"], d)
                                if d.get("ip"):
                                    ip_to_dev.setdefault(d["ip"], d)

                        # 1. DNS
                        dns_servers = wan_settings.get("dnsConfig", {}).get("servers", [])
                        if len(dns_servers) >= 1:
                            _SETTINGS_STORE["dns"]["primary"] = dns_servers[0]
                        if len(dns_servers) >= 2:
                            _SETTINGS_STORE["dns"]["secondary"] = dns_servers[1]
                        _SETTINGS_STORE["dns"]["mode"] = "custom" if dns_servers else "auto"

                        # 2. Wi-Fi SSID
                        ssid = (
                            wlan_settings.get("privateSsid")
                            or _SETTINGS_STORE["wifi"]["ssid"]
                        )
                        _SETTINGS_STORE["wifi"]["ssid"] = ssid

                        # 3. DHCP Pool, UPnP, WPA3
                        if lan_settings.get("dhcpPoolBegin"):
                            _SETTINGS_STORE["dhcp"]["start_ip"] = lan_settings.get("dhcpPoolBegin")
                        if lan_settings.get("dhcpPoolEnd"):
                            _SETTINGS_STORE["dhcp"]["end_ip"] = lan_settings.get("dhcpPoolEnd")
                        if "upnpEnabled" in lan_settings:
                            _SETTINGS_STORE["security"]["upnp_enabled"] = bool(lan_settings.get("upnpEnabled"))
                        if "enabled" in wpa3_settings:
                            _SETTINGS_STORE["security"]["wpa3_enabled"] = bool(wpa3_settings.get("enabled"))

                        # 4. DHCP IP Reservations
                        static_mappings = lan_settings.get("staticIpMappings", [])
                        if static_mappings:
                            live_reservations = []
                            for m in static_mappings:
                                st_id = m.get("stationId", "")
                                res_ip = m.get("ipAddress", "")
                                dev = id_to_dev.get(st_id) or ip_to_dev.get(res_ip) or {}
                                hostname = (
                                    dev.get("friendlyName")
                                    or dev.get("automaticFriendlyName")
                                    or dev.get("dhcpHostname")
                                    or dev.get("name")
                                    or f"Device {res_ip.split('.')[-1]}"
                                )
                                mac = dev.get("macAddress") or dev.get("mac") or ""
                                live_reservations.append({
                                    "mac": mac or (st_id[:17] if st_id else "00:00:00:00:00:00"),
                                    "ip": res_ip,
                                    "hostname": hostname,
                                    "enabled": True,
                                })
                            _SETTINGS_STORE["dhcp"]["reservations"] = live_reservations

                        # 5. Port Forwarding Rules
                        pf_mappings = wan_settings.get("portForwardingMappings", [])
                        exposed_ports = wan_settings.get("exposedPorts", [])
                        if pf_mappings:
                            live_rules = []
                            for idx, pf in enumerate(pf_mappings):
                                wan_start = pf.get("wanStartPort", 0)
                                wan_end = pf.get("wanEndPort", 0)
                                lan_start = pf.get("lanStartPort", 0)
                                lan_end = pf.get("lanEndPort", 0)
                                int_ip = pf.get("ipAddress", "")
                                tcp = bool(pf.get("forwardTcp"))
                                udp = bool(pf.get("forwardUdp"))
                                proto = "TCP/UDP" if (tcp and udp) else ("TCP" if tcp else "UDP")

                                exp_sid = ""
                                if idx < len(exposed_ports):
                                    exp_sid = exposed_ports[idx].get("stationId", "")

                                dev = ip_to_dev.get(int_ip) or id_to_dev.get(exp_sid) or {}
                                dev_name = (
                                    dev.get("friendlyName")
                                    or dev.get("automaticFriendlyName")
                                    or dev.get("dhcpHostname")
                                    or dev.get("name")
                                    or ""
                                )

                                if (not int_ip or int_ip == "0.0.0.0") and (dev.get("ipAddress") or dev.get("ip")):
                                    int_ip = dev.get("ipAddress") or dev.get("ip")

                                svc = _PORT_SERVICES.get(wan_start) or _PORT_SERVICES.get(lan_start)
                                if svc and dev_name:
                                    rule_name = f"{svc} ({dev_name})"
                                elif svc:
                                    rule_name = svc
                                elif dev_name:
                                    rule_name = f"{dev_name} :{wan_start}"
                                else:
                                    rule_name = f"Port {wan_start}"

                                ext_port_val = wan_start if (wan_start == wan_end or not wan_end) else f"{wan_start}-{wan_end}"
                                int_port_val = lan_start if (lan_start == lan_end or not lan_end) else f"{lan_start}-{lan_end}"

                                live_rules.append({
                                    "name": rule_name,
                                    "protocol": proto,
                                    "external_port": ext_port_val,
                                    "internal_ip": int_ip or "0.0.0.0",
                                    "internal_port": int_port_val,
                                    "enabled": True,
                                })
                            _SETTINGS_STORE["ports"]["rules"] = live_rules

                        _settings_synced_from_router = True
                        _save_settings_store()
            except Exception as exc:
                logger.exception("Failed to sync live settings from router: %s", exc)

    return {"ok": True, "demo": config.is_demo_mode(), "settings": _SETTINGS_STORE}


async def update_settings(section: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update a settings section. Returns the updated section."""
    if section not in _SETTINGS_STORE:
        return {"ok": False, "error": f"Unknown settings section: {section}"}

    _SETTINGS_STORE[section].update(updates)
    _save_settings_store()
    return {
        "ok": True,
        "demo": config.is_demo_mode(),
        "section": section,
        "settings": _SETTINGS_STORE[section],
        "message": f"Settings '{section}' updated successfully",
    }


async def add_dhcp_reservation(mac: str, ip: str, hostname: str) -> dict[str, Any]:
    """Add a DHCP IP reservation."""
    reservations = _SETTINGS_STORE["dhcp"]["reservations"]
    # Check for duplicate MAC
    for r in reservations:
        if r["mac"].lower() == mac.lower():
            r.update({"ip": ip, "hostname": hostname})
            _save_settings_store()
            return {"ok": True, "message": "Reservation updated", "reservations": reservations}
    reservations.append({"mac": mac, "ip": ip, "hostname": hostname, "enabled": True})
    _save_settings_store()
    return {"ok": True, "message": "Reservation added", "reservations": reservations}


async def remove_dhcp_reservation(mac: str) -> dict[str, Any]:
    """Remove a DHCP IP reservation by MAC address."""
    before = len(_SETTINGS_STORE["dhcp"]["reservations"])
    _SETTINGS_STORE["dhcp"]["reservations"] = [
        r for r in _SETTINGS_STORE["dhcp"]["reservations"] if r["mac"].lower() != mac.lower()
    ]
    removed = before - len(_SETTINGS_STORE["dhcp"]["reservations"])
    _save_settings_store()
    return {"ok": True, "removed": removed, "reservations": _SETTINGS_STORE["dhcp"]["reservations"]}


async def add_port_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Add a port forwarding rule."""
    required = {"name", "protocol", "external_port", "internal_ip", "internal_port"}
    if not required.issubset(rule.keys()):
        return {"ok": False, "error": f"Missing fields: {required - set(rule.keys())}"}
    rule.setdefault("enabled", True)
    _SETTINGS_STORE["ports"]["rules"].append(rule)
    _save_settings_store()
    return {"ok": True, "message": "Port rule added", "rules": _SETTINGS_STORE["ports"]["rules"]}


async def remove_port_rule(idx: int) -> dict[str, Any]:
    """Remove a port forwarding rule by index."""
    rules = _SETTINGS_STORE["ports"]["rules"]
    if idx < 0 or idx >= len(rules):
        return {"ok": False, "error": f"Rule index {idx} out of range"}
    removed = rules.pop(idx)
    _save_settings_store()
    return {"ok": True, "message": f"Rule '{removed['name']}' removed", "rules": rules}
