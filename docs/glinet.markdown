---
title: GL-iNet
description: Instructions on how to integrate GL.iNet routers into Home Assistant.
ha_category:
  - Binary sensor
  - Button
  - Diagnostics
  - Presence detection
  - Sensor
  - Switch
ha_release: "2024.1"
ha_domain: glinet
ha_config_flow: true
ha_codeowners:
  - "@HarvsG"
ha_iot_class: Local Polling
ha_platforms:
  - button
  - device_tracker
  - diagnostics
  - sensor
  - switch
ha_integration_type: hub
ha_quality_scale: platinum
---

The **GL-iNet** integration allows you to monitor and control your [GL.iNet](https://www.gl-inet.com/) router powered by GL.iNet API v4, perform presence detection for connected client devices, toggle Wi-Fi interfaces, control status LEDs, manage VPN client connections, and view system metrics.

## Supported Devices

Support is available for GL.iNet router models running GL.iNet firmware 4.x with API v4 enabled:

- **GL-MT6000** (Flint 2)
- **GL-MT3000** (Beryl AX)
- **GL-B1300** (Convexa-B)
- Other GL.iNet hardware models running firmware version 4.0 or newer.

## Prerequisites

To connect Home Assistant to your GL.iNet router, ensure:

1. **Network Connectivity**: Your Home Assistant instance must be able to reach the router's IP address (default: `192.168.8.1`) over HTTP or HTTPS.
2. **Administrator Credentials**: You must use the administrator password used to log into the router's web admin panel. The default username on GL.iNet devices is `root`.
3. **SSL Certificate**: If using HTTPS with local self-signed certificates, you can disable SSL certificate verification during setup or in the integration options.

> [!IMPORTANT] > **Default Admin Password Warning**:
> Using the factory default password (`goodlife`) poses a security risk. If your router is using the default password, Home Assistant creates a repair issue advising you to update your admin password immediately.

---

## Configuration

To add the **GL-iNet** integration to your Home Assistant instance:

1. Navigate to **Settings** > **Devices & Services**.
2. If your router was auto-discovered via DHCP, select **Configure** on the discovery card. Otherwise, select **Add Integration** and search for **GL-iNet**.
3. Complete the setup form with your router credentials.

### Setup Parameters

| Parameter                  | Type      | Required | Default              | Description                                                                                             |
| :------------------------- | :-------- | :------- | :------------------- | :------------------------------------------------------------------------------------------------------ |
| **Host**                   | `string`  | **Yes**  | `http://192.168.8.1` | The hostname or IP address of your GL.iNet router (HTTP or HTTPS).                                      |
| **Username**               | `string`  | **Yes**  | `root`               | The administrator username used to log into the router.                                                 |
| **Password**               | `string`  | **Yes**  | —                    | The administrator password used to log into your router's admin interface.                              |
| **Consider home**          | `integer` | No       | `180`                | Seconds to wait before marking a disconnected device as away (0–900 seconds).                           |
| **Verify SSL certificate** | `boolean` | No       | `false`              | Enable SSL certificate verification for HTTPS connections (disable for local self-signed certificates). |

### Integration Options

To adjust integration settings after setup, navigate to **Settings** > **Devices & Services** > **GL-iNet** > **Configure**:

| Option                     | Default  | Description                                                                                                                                                     |
| :------------------------- | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Consider home**          | `180`    | Adjust the presence detection timeout in seconds.                                                                                                               |
| **Verify SSL certificate** | `false`  | Enable or disable SSL certificate validation for HTTPS connections.                                                                                             |
| **Randomized-MAC devices** | `Ignore` | Configure handling for clients using MAC randomization: **Ignore (don't create entities)**, **Track (disabled by default)**, or **Track (enabled by default)**. |

---

## Supported Functions

The GL-iNet integration provides the following platforms and entities:

### 📡 Device Tracker

- **Client Presence Tracking**: Automatically tracks devices connected directly or indirectly across LAN ports and Wi-Fi radios (`2.4GHz`, `5GHz`, `6GHz`, `MLO`, `Guest`).
- **Entity State**: Reports `home` or `not_home` based on the configured _Consider home_ interval.
- **Attributes**: Exposes MAC address, primary IP address, interface connection type, and last reachable timestamp.

### 🎛️ Switches

- **Wi-Fi Access Points**: Toggle individual Wi-Fi radios and SSIDs (e.g. 2.4GHz, 5GHz, Guest Wi-Fi) on or off. Attributes include SSID, guest flag, hidden status, and encryption mode.
- **WireGuard Clients**: Independent toggles for configured WireGuard VPN client tunnels.
- **Tailscale**: Toggle the router's Tailscale connection on or off, with LAN subnet exposure attributes.
- **LED Control**: Turn the router's hardware status LEDs on or off.

### 📊 Diagnostic Sensors

- **CPU Temperature**: Real-time processor temperature in °C (on hardware models supporting temperature reporting).
- **CPU Load Averages**: 1-minute (`load_avg1`), 5-minute (`load_avg5`), and 15-minute (`load_avg15`) system load averages.
- **Memory Usage**: Percentage of RAM used, with total and free memory attributes.
- **Flash Storage Usage**: Percentage of flash storage used, with total and free flash attributes.
- **System Uptime**: Boot timestamp sensor (`timestamp` device class) with drift suppression.
- **Connected Clients**: Total connected client count, with attributes and individual breakdown sensors for LAN clients, Router Wi-Fi clients, and Guest clients.
- **WAN Status**: Enums (`connected`, `failing`, `disconnected`) showing state per WAN interface.

### 🔘 Buttons

- **Reboot Router**: Trigger a safe restart of the GL.iNet router.

---

## Common Use Cases & Automation Examples

### 1. Darken Status LEDs at Night

Turn off the router's status LEDs at bedtime and turn them back on in the morning:

```yaml
alias: Router - Darken LEDs at Night
triggers:
  - trigger: time
    at: "23:00:00"
    id: night
  - trigger: time
    at: "07:00:00"
    id: morning
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: night
        sequence:
          - action: switch.turn_off
            target:
              entity_id: switch.gl_mt6000_led
      - conditions:
          - condition: trigger
            id: morning
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.gl_mt6000_led
```

### 2. Reboot Router on Weekly Schedule

Automatically reboot the router early Sunday morning:

```yaml
alias: Router - Weekly Reboot
triggers:
  - trigger: time
    at: "04:00:00"
conditions:
  - condition: time
    weekday:
      - sun
actions:
  - action: button.press
    target:
      entity_id: button.gl_mt6000_reboot
```

### 3. Presence-Based Tailscale Toggle

Automatically enable Tailscale VPN when away from home:

```yaml
alias: Router - Enable Tailscale When Away
triggers:
  - trigger: zone.left
    target:
      entity_id: person.admin
    options:
      zone: zone.home
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.gl_mt6000_tailscale
```

---

## Known Limitations

- **Firmware API Version**: This integration targets GL.iNet firmware 4.x (API v4). Older firmware (3.x) is not supported.
- **Scanner Entities Disabled by Default**: In compliance with Home Assistant integration quality standards, device tracker (scanner) entities for newly discovered client devices that are not already associated with an existing Home Assistant device registry entry are **disabled by default**. This prevents network routers from cluttering Home Assistant with transient or single-use network entities. To use a client for presence detection, manually enable its entity under **Settings** > **Devices & Services** > **Entities**. Clients with randomized MAC addresses follow the "Randomized-MAC devices" option configuration instead.
- **Downstream Network Topology**: Clients connected through downstream switches, mesh nodes, or secondary access points reach the router via its LAN ports and are reported under LAN client counts even if connected over Wi-Fi.
- **Smartphone MAC Address Randomization**: Mobile devices with MAC randomization enabled generate dynamic MAC addresses when re-connecting. It is recommended to disable MAC randomization for your home Wi-Fi network on iOS and Android for reliable presence tracking.

---

## Troubleshooting

### Authentication Errors

If the router admin password changes, Home Assistant will prompt a **Re-authentication** flow after a few minutes. Navigate to **Settings** > **Devices & Services** > **GL-iNet** and enter your updated password.

### SSL Certificate Failures

If connecting via `https://` with a self-signed certificate, ensure **Verify SSL certificate** is disabled in the integration configuration or options menu.

### Diagnostic Logs

To collect detailed troubleshooting logs, enable debug logging [via the UI](https://www.home-assistant.io/docs/configuration/troubleshooting/#enabling-debug-logging) or in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.glinet: debug
    gli4py: debug
```
