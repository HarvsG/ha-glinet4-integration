# GL-iNet Integration for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/HarvsG/ha-glinet4-integration?style=flat-square)](https://github.com/HarvsG/ha-glinet4-integration/releases)
[![Tests](https://img.shields.io/github/actions/workflow/status/HarvsG/ha-glinet4-integration/tests.yml?label=tests&style=flat-square)](https://github.com/HarvsG/ha-glinet4-integration/actions/workflows/tests.yml)
[![Hassfest](https://img.shields.io/github/actions/workflow/status/HarvsG/ha-glinet4-integration/hassfest.yml?label=hassfest&style=flat-square)](https://github.com/HarvsG/ha-glinet4-integration/actions/workflows/hassfest.yml)
[![HACS Validation](https://img.shields.io/github/actions/workflow/status/HarvsG/ha-glinet4-integration/validate.yml?label=HACS&style=flat-square)](https://github.com/HarvsG/ha-glinet4-integration/actions/workflows/validate.yml)
[![Linting](https://img.shields.io/github/actions/workflow/status/HarvsG/ha-glinet4-integration/linting.yml?label=linting&style=flat-square)](https://github.com/HarvsG/ha-glinet4-integration/actions/workflows/linting.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)
[![License: Apache-2.0](https://img.shields.io/github/license/HarvsG/ha-glinet4-integration?style=flat-square)](LICENSE)

A Home Assistant custom component for **GL.iNet routers** powered by [their API version 4](https://dev.gl-inet.com/api/) via the [`gli4py`](https://github.com/HarvsG/gli4py) library.

> [!IMPORTANT]
> This integration requires **Python 3.14** or later (uses [PEP 758](https://peps.python.org/pep-0758/) exception syntax).

> [!NOTE]
> GL.iNet no longer publicly documents API v4, so the longevity of this integration relies on API reverse-engineering and may change across future firmware versions.
> Contributions are warmly welcomed! See the [TODO list](#todo) or search for `#TODO` comments across the codebase.

---

## Features

### 📡 Device Tracker

- **Automatic Client Tracking**: Tracks devices connected directly or indirectly to your GL.iNet router across wired LAN and wireless interfaces.
- **Broad Interface Support**: Identifies connections on `2.4GHz`, `5GHz`, `6GHz`, `MLO`, `LAN`, `Dongle`, and `Guest` networks.
- **Detailed Attributes**: Exposes MAC address, IP address, connection interface type, and last seen timestamp (`last_time_reachable`).
- **Configurable Presence Timeout**: Customize the "Consider Home" duration in seconds to prevent devices flapping when they enter low-power sleep.
- **Randomized MAC Handling**: Choose whether clients using randomized MAC addresses are ignored (default), tracked as disabled, or tracked as enabled.

> [!NOTE]
>
> In line with Home Assistant standards, client tracker entities are **disabled by default** unless their MAC is already known to another integration. You can enable tracking for any client under **Settings** > **Devices & Services** > **Entities**. Clients with randomized MACs follow the "Randomized-MAC devices" option instead.

> [!TIP]
> Modern smartphones enable MAC address randomisation by default. To ensure reliable presence detection, disable MAC randomisation for your home Wi-Fi network on [Android](https://source.android.com/docs/core/connect/wifi-mac-randomization-behavior) and [iOS](https://support.apple.com/en-gb/102509).

### 🎛️ Switches

- **Wi-Fi Access Points**: Enable or disable individual Wi-Fi radios/interfaces (e.g., 2.4GHz, 5GHz, and Guest networks) directly from Home Assistant. Includes attributes for SSID, guest status, hidden SSID, and encryption mode.
- **WireGuard Clients**: Independent toggle switches for each configured WireGuard VPN client tunnel to connect or disconnect on demand.
- **Tailscale**: Toggle the router's Tailscale connection on and off, with LAN subnet exposure visibility.
- **LED Control**: Turn the router's status LEDs on or off (mirrors the LED toggle on the GL.iNet admin panel's System overview page) — handy for darkening the router at night.

### 📊 Diagnostic Sensors

- **CPU Temperature**: Real-time processor temperature in °C (dynamically added on hardware models that report temperature).
- **CPU Load**: 1-minute, 5-minute, and 15-minute system load averages (`load_avg1`, `load_avg5`, `load_avg15`).
- **Memory Usage**: Percentage of RAM utilized, with total and free memory attributes.
- **Flash Storage Usage**: Percentage of flash storage used, with total and free storage attributes.
- **System Uptime**: Derived boot timestamp sensor (`timestamp` device class) with drift suppression.
- **Connected Clients**: Total number of client devices currently connected, refreshed every poll, with a `wired`/`wireless`/`guest` breakdown exposed as attributes and as individual diagnostic sensors (LAN, Router Wi-Fi and Guest clients). These sensors are disabled by default; enable them from the router's device page in Home Assistant.
  - _Note_: Wi-Fi counts only include clients connected directly to the router's own radios. Clients connected through a downstream access point, mesh node or switch reach the router over its LAN ports, so they are counted as LAN clients.

### 🔘 Buttons

- **Reboot Router**: Safely reboot the router directly from Home Assistant or trigger it within automations.

### ⚙️ Configuration & Maintenance

- **DHCP Discovery**: Automatically detected on your local network (matches `*gl-*` hostnames and GL.iNet vendor MAC prefixes).
- **UI Config Flow**: Simple web-based setup using router host IP/URL and administrator credentials.
- **Re-authentication**: Automatic notification and re-auth flow when the router's login password changes.
- **Reconfiguration**: Easily modify host URL or connection parameters without re-creating entities.
- **Options Flow**: Adjust the "Consider Home" presence threshold and configure "Randomized-MAC devices" handling anytime without restarting Home Assistant.
- **Data Updates & Polling**: Uses Home Assistant's standard `DataUpdateCoordinator` with tiered polling:
  - **Fast tier (30 seconds)**: System status, WAN interface states, and connected client presence.
  - **Slow tier (60 seconds)**: Wi-Fi interface configurations, VPN connection states, LED state, and non-configured endpoint probes (probed at startup only).
  - **Dynamic Entity Discovery**: Newly discovered client devices and WAN interfaces are registered automatically on poll without reloading.
- **Diagnostics**: Full diagnostic support with automatic redaction of passwords, MACs, and tokens.

---

## Installation

### Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HarvsG&repository=ha-glinet4-integration&category=integration)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. In Home Assistant, navigate to **HACS** > **Integrations**.
3. Click the three dots in the top-right corner and select **Custom repositories**.
4. Add `https://github.com/HarvsG/ha-glinet4-integration` with category **Integration**.
5. Click **Add**, search for **GL-iNet**, and select **Download**.
6. Restart Home Assistant.

### Manual Installation

1. Download the [latest release](https://github.com/HarvsG/ha-glinet4-integration/releases) zip archive.
2. Unpack and copy the `custom_components/glinet` directory into your Home Assistant installation's `config/custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, navigate to **Settings** > **Devices & Services**.
2. If your router was discovered automatically via DHCP, click **Configure** on the discovery card. Otherwise, click **Add Integration** and search for **GL-iNet**.
3. Fill in the connection settings:
   - **Host**: The IP or URL of your router (defaults to `http://192.168.8.1`).
   - **Username**: Router admin username (default: `root`).
   - **Password**: The administrator password used to log in to the GL.iNet web admin panel.
   - **Consider Home**: Number of seconds to consider a device still connected after it was last reachable (default: `180`).

For full integration documentation, supported device lists, automation examples, and troubleshooting guides, see [`docs/glinet.markdown`](docs/glinet.markdown).

---

## Removal

1. In Home Assistant, navigate to **Settings** > **Devices & Services**.
2. Find the **GL-iNet** integration card.
3. Click the three dots menu icon (⋮) and select **Delete**.
4. Confirm deletion when prompted.

---

## Development Setup

If you want to contribute to this integration:

1. Follow the [Home Assistant Core development environment guide](https://developers.home-assistant.io/docs/development_environment/) (VS Code Dev Containers recommended).
2. Clone this repository:
   ```bash
   git clone https://github.com/HarvsG/ha-glinet4-integration.git /workspaces/glinet
   ```
3. Link the integration into your Home Assistant core dev environment:
   ```bash
   mkdir -p /workspaces/core/config/custom_components
   ln -s /workspaces/glinet/custom_components/glinet /workspaces/core/config/custom_components/glinet
   ```
4. Install development dependencies with mock support:
   ```bash
   uv sync
   # or into an existing environment:
   pip install "gli4py[mock]"
   ```
5. Run tests:
   ```bash
   uv run pytest
   ```

> [!IMPORTANT] > **Python 3.13+ `aiohttp` Notice**: `aiohttp` strictly rejects HTTP responses with duplicate header keys in dev mode (which GL.iNet firmware often returns). When debugging in VS Code, add `"PYTHONASYNCIODEBUG": ""` to your `env` configuration in `.vscode/launch.json`:
>
> ```json
> {
>   "configurations": [
>     {
>       "name": "Home Assistant",
>       "type": "debugpy",
>       "request": "launch",
>       "module": "homeassistant",
>       "justMyCode": false,
>       "args": ["--debug", "-c", "config"],
>       "env": {
>         "PYTHONASYNCIODEBUG": ""
>       }
>     }
>   ]
> }
> ```

---

## TODO

### 🏗️ Architecture & Core

- [ ] **Unified VPN Switch Architecture**: Abstract VPN switches to be platform and protocol-agnostic, supporting WireGuard, OpenVPN, Shadowsocks, and Tor clients & servers programmatically (e.g., via `router/vpn/status`).

### 💡 Features Under Consideration

- [ ] **WAN Access control**: Implement a WAN on/off switch for each client device to enable control of IoT and parental controls
- [ ] **Port Forwarding**: Implement switches to enable/disable port-forwarding rules
- [ ] **Network & Bandwidth Sensors**: Real-time upload and download rate sensors for devices.
- [ ] **VPN Policy Routing**: Automate switching VPN client routing policies per device (e.g. for bypassing geofilters in automations).
- [ ] **Cellular & Tethering**: USB tethering and cellular modem control for failover internet automations.
- [ ] **SMS Notifications**: Expose router cellular modem SMS support via a notify platform.
- [ ] **Firmware Management**: Firmware update status sensor and upgrade trigger (with safety warnings).
- [ ] **Smart Home Protocols**: Explore integration with GL.iNet smart home Bluetooth LE and OpenThread border router endpoints.

### ✅ Completed

- [x] **Home Assistant Quality Scale**: Reached **Platinum** quality scale tier with full documentation ([`docs/glinet.markdown`](docs/glinet.markdown)).
- [x] **Switch from `.get()` to Attributes**: Replaced dictionary `.get()` calls with strongly-typed `gli4py` class attributes across router, sensors, switches, and diagnostics.
- [x] **Device Registry Pruning**: Implemented `async_remove_config_entry_device` and device cleanup logic to support removing stale device tracker entities in Home Assistant ([documentation](https://developers.home-assistant.io/docs/device_registry_index/#removing-devices)).
- [x] Comprehensive automated test suite with real router hardware fixtures and upstream mock router (`pytest`, `gli4py[mock]`).
- [x] Strict typing (`mypy --strict`) enforced in CI across integration and tests.
- [x] Multi-WAN interface connection status sensors.
- [x] DHCP Auto-discovery (`*gl-*` hostnames and MAC prefix).
- [x] Automatic re-authentication flow when admin credentials change.
- [x] Reconfiguration and options flows.
- [x] Wi-Fi access point switches (2.4GHz, 5GHz, Guest networks).
- [x] LED indicator control switch.
- [x] System diagnostic sensors (CPU temp/load, memory, flash, uptime) & reboot button.
- [x] Connected clients sensors (total plus wired / wireless / guest breakdown).
- [x] **Strict Typing**: Add complete typing to upstream [`gli4py`](https://github.com/HarvsG/gli4py) and enforce strict typing with `mypy --strict` in CI.
- [x] **Error Recovery**: Further refine error recovery to handle transient empty client lists immediately following a router reboot.
- [x] **HTTPS Support**: Add support for `https://` router communication with optional handling for local self-signed certificates.
- [x] **Migrate to `DataUpdateCoordinator`**: Refactor `GLinetRouter` away from custom `async_track_time_interval` polling and manual dispatcher signals to Home Assistant's standard `DataUpdateCoordinator` pattern

---

## Tested Hardware

The integration is known to work on the following models:

- **GL-MT1300** (Beryl)
- **GL-B1300** (Convexa-B)
- **GL-MT6000** (Flint 2)

_Have you tested this on another GL.iNet router model? Please open an issue or pull request to add it to the list!_

---

## Dependencies

- [`gli4py`](https://github.com/HarvsG/gli4py) - Python client library for the GL.iNet API v4.
