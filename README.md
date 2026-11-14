# 🏠 Google Nest Wifi Pro Desktop Dashboard

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hardware](https://img.shields.io/badge/Hardware-Nest%20Wifi%20Pro%20(Wi--Fi%206E)-teal.svg)](#supported-hardware)

A lightweight, modern desktop web dashboard for monitoring, diagnosing, and managing your **Google Nest Wifi Pro** mesh network directly from your PC browser—without relying on the Google Home mobile app.

---

## ✨ Features

- **🌐 Live Network Overview**:
  - Real public WAN IP address detection and router gateway IP.
  - Active SSID / Wi-Fi Network Name.
  - Live WAN status indicator with custom upstream DNS servers.
  - System uptime and network load tracking.

- **⚡ Gigabit WAN Speed Test**:
  - Live download and upload gauges (supporting Gigabit+ speeds) with conic-gradient animations.
  - Real-time latency tracking and historical timestamp.
  - **One-click "Run Speed Test"** button to execute a live WAN diagnostic on the primary node.

- **🕸️ Mesh Topology Visualization**:
  - Visual node cards for your Primary Gateway and all Mesh Points.
  - Displays room names (e.g., *Basement*, *Bedroom*, *Family Room*, *Living Room*).
  - Individual connected device count per mesh point.
  - Wi-Fi backhaul signal quality bars vs. Gigabit wired uplink status.
  - Node IP address and firmware version display.
  - Individual mesh node restart buttons with safety confirmation dialogs.

- **📱 Connected Devices Management**:
  - Comprehensive, real-time client table.
  - Auto-categorized device types with custom SVG icons (smart TVs, gaming consoles, PCs, smartphones, smart home appliances, IoT hubs).
  - Real-time Wi-Fi band identification: **6GHz (Wi-Fi 6E)**, **5GHz**, **2.4GHz**, and **Gigabit Wired**.
  - **Online vs. Offline detection**: inactive/disconnected devices cleanly categorized as `Offline`.
  - Client bandwidth usage tracking.
  - **One-Click Internet Pause / Unpause** per device.
  - **QoS Device Prioritization Boost** (1, 2, 4, or 6 hours).
  - Instant client-side search and multi-column sorting.

- **🛡️ Out-of-the-Box Demo Mode**:
  - Fully functional simulated environment featuring 4 mesh points and 18 devices for testing the UI without Google credentials.

---

## 🛠️ Tech Stack & Architecture

- **Backend**: Python 3.10+, Flask, Flask-CORS, `aiohttp`, `googlewifi` client library.
- **Async Concurrency**: Thread-safe persistent background event loop bridging synchronous Flask workers with async Google Cloud / gRPC foyer endpoints.
- **Frontend**: Vanilla HTML5, CSS Grid / Flexbox, Material Design 3 dark palette, and ES6+ JavaScript. No external CDNs or heavy frameworks required.

```
┌────────────────────────────────────────────────────────┐
│                   Web Browser UI                       │
│             (http://localhost:5000)                    │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP / REST API
┌──────────────────────────▼─────────────────────────────┐
│                 Flask Application (app.py)             │
│            • Background Loop Thread Safety             │
│            • Route Controllers & Static Asset Server   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│              Wifi Client (wifi_client.py)              │
│       • TTL In-Memory Caching (30s)                    │
│       • Hardware Schema Normalizer & Data Adapter      │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼──────────────┐ ┌─────────▼──────────────┐
│  Google Cloud Foyer API     │ │  Local LAN Diagnostics │
│  (googlewifi library)       │ │  (192.168.1.1:8443)    │
└─────────────────────────────┘ └────────────────────────┘
```

---

## 🚀 Quick Start (Windows)

### 1. Installation

Clone this repository and ensure Python 3.10+ is installed:
```powershell
git clone <YOUR_REPO_URL>
cd nest-wifi-dashboard
```

### 2. Launching the App
Double-click **`start.bat`** (or run in PowerShell):
```powershell
.\start.bat
```
The launcher will automatically configure a virtual environment, install requirements, and open `http://localhost:5000` in your default browser.

### 3. Running as a Background Service
You can run the dashboard silently in the background (no console window) so it is always accessible at `http://localhost:5000`:

* **From the Settings UI:**
  Navigate to **Settings** ➔ **System** ➔ **Background Service**, and toggle **"Run in Background on Startup"**.
* **1-Click Launchers (Silent / Windowless):**
  * `start_background.vbs`: Starts the app completely headless via `pythonw.exe` without opening a terminal window.
  * `stop_background.bat`: Halts the background service.
  * `install_service.bat`: Registers the dashboard to automatically start on Windows login.
  * `uninstall_service.bat`: Unregisters the startup service.
* **Command Line Flags:**
  ```powershell
  python run.py --no-browser        # Launch without opening a browser window
  python run.py --service           # Run in headless service mode
  python run.py --install-service   # Register autostart for the current user
  python run.py --uninstall-service # Remove autostart registration
  python run.py --status            # Output JSON service status
  ```

---

## 🔐 Connecting Your Real Google Nest Wifi Network

Because Google has locked down router APIs to the Google Home mobile app, accessing your network programmatically requires authenticating via Google Play Services OAuth:

1. Double-click **`setup_auth.bat`** (or run `python auth_helper.py`).
2. Enter your Google account email address.
3. The script opens Google's official setup endpoint:  
   👉 `https://accounts.google.com/EmbeddedSetup`
4. Sign in with your Google account and complete 2-Step Verification.
5. Click **"I agree"** on any consent prompt.
6. When the page stops at a loading/spinning screen (this is normal and expected):
   - Press **F12** (Developer Tools).
   - Navigate to the **Application** tab (Chrome/Edge/Brave) or **Storage** tab (Firefox).
   - In the left sidebar, expand **Storage** ➔ **Cookies** ➔ click `https://accounts.google.com`.
   - Find the cookie named **`oauth_token`**.
   - Copy its value (starts with `oauth2_4/...`) and paste it into the terminal.
7. The helper script automatically exchanges it for a permanent **Master Token** and writes it to your local `.env` file.
8. Re-run **`start.bat`** to enjoy your live dashboard!

---

## ⚙️ Configuration (`.env`)

Configuration parameters are loaded from `.env`:

```env
# Google Account
GOOGLE_EMAIL=your.email@gmail.com
GOOGLE_MASTER_TOKEN=aas_et/...
ANDROID_ID=a43e715556f4ffd0

# Network Settings
ROUTER_IP=192.168.1.1
FLASK_PORT=5000
REFRESH_INTERVAL=30

# Force mock simulation (true/false)
FORCE_DEMO_MODE=false
```

> **Note:** Never commit your `.env` file to source control. It is ignored by default in `.gitignore`.

---

## 🔌 API Reference

The backend exposes a clean REST API consumed by the dashboard:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Network name, WAN connection, Public IP, and device totals |
| `GET` | `/api/access-points` | List of mesh nodes with roles, IPs, client counts, and status |
| `GET` | `/api/devices` | All registered devices with status, connection band, and IP |
| `GET` | `/api/speed-test` | Latest WAN download, upload, and latency metrics |
| `POST` | `/api/speed-test` | Trigger a new live WAN speed test |
| `POST` | `/api/devices/<id>/pause` | Toggle internet access for a device (`{"paused": true/false}`) |
| `POST` | `/api/devices/<id>/prioritize` | Set QoS bandwidth prioritization (`{"hours": 1-6}`) |
| `POST` | `/api/access-points/<id>/restart` | Reboot an individual mesh node |
| `GET` | `/api/local-info` | Hardware model, firmware version, and gateway diagnostic specs |
| `GET` | `/api/config` | Non-sensitive server configuration & runtime mode |

---

## 📁 Project Structure

```
nest-wifi-dashboard/
├── .env.example          # Environment template
├── .gitignore            # Ignores .venv, .credentials.enc, settings_store.json, etc.
├── app.py                # Flask application & multi-threaded async runner
├── auth_helper.py        # Interactive Google OAuth token exchange wizard
├── config.py             # Configuration loader with sensible defaults
├── credentials.py        # Windows DPAPI encrypted token store
├── service_manager.py    # Background service & autostart manager
├── README.md             # Project documentation
├── requirements.txt      # Python dependencies
├── run.py                # Application entrypoint & CLI service controller
├── setup_auth.bat        # Windows 1-click authentication wizard
├── start.bat             # Windows 1-click foreground launcher
├── start_background.vbs  # Silent windowless background runner
├── start_background.bat  # Background launcher batch wrapper
├── stop_background.bat   # Process terminator for port 5000
├── install_service.bat   # Windows autostart service installer
├── uninstall_service.bat # Windows autostart service uninstaller
├── static/
│   ├── index.html        # Single-page modern dashboard UI
│   └── settings.html     # Settings UI (DNS, DHCP, Ports, Wi-Fi, Service, Auth)
└── wifi_client.py        # Async data adapter for Google Wifi & local endpoints
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
