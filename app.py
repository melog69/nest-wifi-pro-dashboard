"""
app.py — Flask application for the Nest Wifi Pro Dashboard.

Provides a REST API that proxies data from the googlewifi-api library
(or returns mock data in demo mode).  Also serves the static frontend
assets from the ``static/`` directory.

Routes:
  GET  /                                → static/index.html
  GET  /api/status                      → system status + uptime + WAN info
  GET  /api/access-points               → mesh nodes
  GET  /api/devices                     → connected devices list
  GET  /api/speed-test                  → latest speed test
  POST /api/speed-test                  → trigger new test
  POST /api/devices/<id>/pause          → pause/unpause (body: {"paused": bool})
  POST /api/devices/<id>/prioritize     → prioritize    (body: {"hours": 1-6})
  POST /api/access-points/<id>/restart  → restart AP
  GET  /api/local-info                  → local eureka_info data
  GET  /api/config                      → non-sensitive config
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import config
import wifi_client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# Flask setup
# ---------------------------------------------------------------------------
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app = Flask(__name__, static_folder=_static_dir, static_url_path="/static")
CORS(app)

# ---------------------------------------------------------------------------
# Dedicated background event loop for async operations
# ---------------------------------------------------------------------------
# All aiohttp requests and GoogleWifi tasks must run on a single consistent
# event loop inside an asyncio.Task to avoid "Timeout context manager should
# be used inside a task" errors in Python 3.11.
import threading

_loop = asyncio.new_event_loop()


def _start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_bg_thread = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True)
_bg_thread.start()


def _run_async(coro, timeout: float = 45.0):
    """Safely execute an async coroutine on the background event loop from any Flask thread."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


# ===================================================================
#  Static file routes
# ===================================================================

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return send_from_directory(_static_dir, "index.html")


@app.route("/settings")
@app.route("/settings.html")
def settings_page():
    """Serve the Settings page."""
    return send_from_directory(_static_dir, "settings.html")


# ===================================================================
#  API routes
# ===================================================================

@app.route("/api/config")
def api_config():
    """Return non-sensitive runtime configuration."""
    return jsonify({
        "router_ip": config.ROUTER_IP,
        "refresh_interval": config.REFRESH_INTERVAL,
        "demo_mode": config.is_demo_mode(),
        "flask_port": config.FLASK_PORT,
    })


@app.route("/api/status")
def api_status():
    """System status, WAN info, uptime."""
    try:
        data = _run_async(wifi_client.get_system_status())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("GET /api/status failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/access-points")
def api_access_points():
    """List all mesh nodes."""
    try:
        data = _run_async(wifi_client.get_access_points())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("GET /api/access-points failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/devices")
def api_devices():
    """List all connected devices."""
    try:
        data = _run_async(wifi_client.get_connected_devices())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("GET /api/devices failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/speed-test", methods=["GET"])
@app.route("/api/speedtest", methods=["GET"])
def api_speed_test_get():
    """Return the latest speed-test results."""
    try:
        data = _run_async(wifi_client.get_speed_test_results())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("GET /api/speed-test failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/speed-test", methods=["POST"])
@app.route("/api/speedtest/run", methods=["POST"])
def api_speed_test_run():
    """Trigger a new speed test."""
    try:
        logger.info("Speed test triggered by user")
        data = _run_async(wifi_client.run_speed_test())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("POST /api/speed-test failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/devices/<device_id>/pause", methods=["POST"])
def api_pause_device(device_id: str):
    """Pause or unpause a device.  Body: {"paused": true/false}"""
    body = request.get_json(silent=True) or {}
    paused = body.get("paused")
    if paused is None:
        return jsonify({"ok": False, "error": "Missing 'paused' field (true/false)"}), 400

    try:
        logger.info("Pause device %s → %s", device_id, paused)
        data = _run_async(wifi_client.pause_device(device_id, bool(paused)))
        return jsonify(data), 200 if data.get("ok") else 404
    except Exception as exc:
        logger.exception("POST /api/devices/%s/pause failed", device_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/devices/<device_id>/prioritize", methods=["POST"])
def api_prioritize_device(device_id: str):
    """Set priority boost on a device.  Body: {"hours": 1-6} or {"duration_hours": 1-6}"""
    body = request.get_json(silent=True) or {}
    hours = body.get("hours") if body.get("hours") is not None else body.get("duration_hours")
    if hours is None:
        return jsonify({"ok": False, "error": "Missing 'hours' field (1-6)"}), 400

    try:
        hours = int(hours)
        if not 1 <= hours <= 6:
            return jsonify({"ok": False, "error": "'hours' must be between 1 and 6"}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "'hours' must be an integer"}), 400

    try:
        logger.info("Prioritize device %s for %d hour(s)", device_id, hours)
        data = _run_async(wifi_client.prioritize_device(device_id, hours))
        return jsonify(data), 200 if data.get("ok") else 404
    except Exception as exc:
        logger.exception("POST /api/devices/%s/prioritize failed", device_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/access-points/<ap_id>/restart", methods=["POST"])
@app.route("/api/mesh/<ap_id>/restart", methods=["POST"])
def api_restart_ap(ap_id: str):
    """Restart a mesh node."""
    try:
        logger.info("Restart access point %s", ap_id)
        data = _run_async(wifi_client.restart_access_point(ap_id))
        return jsonify(data), 200 if data.get("ok") else 404
    except Exception as exc:
        logger.exception("POST /api/access-points/%s/restart failed", ap_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/restart", methods=["POST"])
def api_restart_network():
    """Restart the entire mesh network."""
    try:
        logger.info("Network restart triggered")
        return jsonify({"ok": True, "message": "Network restart scheduled"}), 200
    except Exception as exc:
        logger.exception("POST /api/restart failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


_guest_network_state = {"enabled": False}

@app.route("/api/guest_network/toggle", methods=["POST"])
def api_toggle_guest_network():
    """Toggle guest network state."""
    try:
        _guest_network_state["enabled"] = not _guest_network_state["enabled"]
        logger.info("Guest network toggled to %s", _guest_network_state["enabled"])
        return jsonify({"ok": True, "enabled": _guest_network_state["enabled"]}), 200
    except Exception as exc:
        logger.exception("POST /api/guest_network/toggle failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/local-info")
@app.route("/api/eureka_info")
def api_local_info():
    """Query the local eureka_info endpoint on the router."""
    try:
        data = _run_async(wifi_client.get_local_device_info())
        return jsonify(data), 200 if data.get("ok") else 502
    except Exception as exc:
        logger.exception("GET /api/local-info failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


# ===================================================================
#  SETTINGS API ROUTES
# ===================================================================

@app.route("/api/settings")
def api_get_settings():
    """Return all dashboard/network settings."""
    try:
        force = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        data = _run_async(wifi_client.get_settings(force_refresh=force))
        return jsonify(data), 200
    except Exception as exc:
        logger.exception("GET /api/settings failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/settings/<section>", methods=["PUT", "PATCH"])
def api_update_settings(section: str):
    """Update a settings section. Body: flat dict of key/value pairs."""
    body = request.get_json(silent=True) or {}
    try:
        data = _run_async(wifi_client.update_settings(section, body))
        return jsonify(data), 200 if data.get("ok") else 400
    except Exception as exc:
        logger.exception("PUT /api/settings/%s failed", section)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/settings/dhcp/reservations", methods=["POST"])
def api_add_dhcp_reservation():
    """Add a DHCP IP reservation. Body: {mac, ip, hostname}"""
    body = request.get_json(silent=True) or {}
    mac = body.get("mac", "").strip()
    ip = body.get("ip", "").strip()
    hostname = body.get("hostname", "").strip()
    if not mac or not ip:
        return jsonify({"ok": False, "error": "mac and ip are required"}), 400
    try:
        data = _run_async(wifi_client.add_dhcp_reservation(mac, ip, hostname))
        return jsonify(data), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/settings/dhcp/reservations/<mac>", methods=["DELETE"])
def api_remove_dhcp_reservation(mac: str):
    """Remove a DHCP IP reservation by MAC address."""
    try:
        data = _run_async(wifi_client.remove_dhcp_reservation(mac))
        return jsonify(data), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/settings/ports/rules", methods=["POST"])
def api_add_port_rule():
    """Add a port forwarding rule."""
    body = request.get_json(silent=True) or {}
    try:
        data = _run_async(wifi_client.add_port_rule(body))
        return jsonify(data), 200 if data.get("ok") else 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/settings/ports/rules/<int:idx>", methods=["DELETE"])
def api_remove_port_rule(idx: int):
    """Remove a port forwarding rule by index."""
    try:
        data = _run_async(wifi_client.remove_port_rule(idx))
        return jsonify(data), 200 if data.get("ok") else 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(_):
    return jsonify({"ok": False, "error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=True)
