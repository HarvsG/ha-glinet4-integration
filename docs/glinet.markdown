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

## Supported devices

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

{% important %}
**Default Admin Password Warning**:
Using the factory default password (`goodlife`) poses a security risk. If your router is using the default password, Home Assistant creates a repair issue advising you to update your admin password immediately.
{% endimportant %}

## Configuration

{% include integrations/config_flow.md %}

{% configuration_basic %}
Host:
description: The hostname or IP address of your GL.iNet router (e.g. `http://192.168.8.1` or `https://192.168.8.1`).
Username:
description: Name of the administrator user (default: `root`).
Password:
description: The password used to log into your router's admin interface.
Consider home:
description: Number of seconds to wait before considering a disconnected device "away" (default: 180 seconds).
Verify SSL certificate:
description: Whether to enforce SSL certificate verification for HTTPS connections. Disable for self-signed certificates.
{% endconfiguration_basic %}

{% include integrations/option_flow.md %}

{% configuration_basic %}
Consider home:
description: Adjust the presence detection timeout in seconds.
Verify SSL certificate:
description: Enable or disable SSL certificate validation.
Randomized-MAC devices:
description: Choose how to handle client devices using MAC address randomization (Ignore, Track as disabled by default, or Track as enabled by default).
{% endconfiguration_basic %}

## Supported Functions

The GL-iNet integration provides the following platforms and entities:

### Device Tracker

- **Client Presence Tracking**: Automatically tracks devices connected directly or indirectly across LAN ports and Wi-Fi radios (`2.4GHz`, `5GHz`, `6GHz`, `MLO`, `Guest`).
- **Entity State**: Reports `home` or `not_home` based on the configured _Consider home_ interval.
- **Attributes**: Exposes MAC address, primary IP address, interface connection type, and last reachable timestamp.

### Switches

- **Wi-Fi Access Points**: Toggle individual Wi-Fi radios and SSIDs (e.g. 2.4GHz, 5GHz, Guest Wi-Fi) on or off. Attributes include SSID, guest flag, hidden status, and encryption mode.
- **WireGuard Clients**: Independent toggles for configured WireGuard VPN client tunnels.
- **Tailscale**: Toggle the router's Tailscale connection on or off, with LAN subnet exposure attributes.
- **LED Control**: Turn the router's hardware status LEDs on or off.

### Sensors

- **CPU Temperature**: Real-time processor temperature in °C (on hardware models supporting temperature reporting).
- **CPU Load Averages**: 1-minute (`load_avg1`), 5-minute (`load_avg5`), and 15-minute (`load_avg15`) system load averages.
- **Memory Usage**: Percentage of RAM used, with total and free memory attributes.
- **Flash Storage Usage**: Percentage of flash storage used, with total and free flash attributes.
- **System Uptime**: Boot timestamp sensor (`timestamp` device class) with drift suppression.
- **Connected Clients**: Total connected client count, with attributes and individual breakdown sensors for LAN clients, Router Wi-Fi clients, and Guest clients.
- **WAN Status**: Enums (`connected`, `failing`, `disconnected`) showing state per WAN interface.

### Buttons

- **Reboot Router**: Trigger a safe restart of the GL.iNet router.

## Common Use Cases & Automation Examples

### 1. Darken Status LEDs at Night

Turn off the router's hardware status LEDs at bedtime and turn them back on in the morning:

```yaml
automation:
  - alias: "Router - Turn Off LEDs at Night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - action: switch.turn_off
        target:
          entity_id: switch.gl_mt6000_led

  - alias: "Router - Turn On LEDs in Morning"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - action: switch.turn_on
        target:
          entity_id: switch.gl_mt6000_led
```

### 2. Reboot Router on Weekly Schedule

Automatically reboot the router early Sunday morning:

```yaml
automation:
  - alias: "Router - Weekly Reboot"
    trigger:
      - platform: time
        at: "04:00:00"
    condition:
      - condition: time
        weekday:
          - sun
    action:
      - action: button.press
        target:
          entity_id: button.gl_mt6000_reboot
```

### 3. Presence-Based VPN Client Toggle

Automatically enable a WireGuard VPN tunnel when leaving home:

```yaml
automation:
  - alias: "Router - Enable VPN When Away"
    trigger:
      - platform: state
        entity_id: zone.home
        to: "0"
    action:
      - action: switch.turn_on
        target:
          entity_id: switch.gl_mt6000_wg_client_home_vpn
```

## Known Limitations

- **Firmware API Version**: This integration targets GL.iNet firmware 4.x (API v4). Older firmware (3.x) is not supported.
- **Downstream Network Topology**: Clients connected through downstream switches, mesh nodes, or secondary access points reach the router via its LAN ports and are reported under LAN client counts.
- **Smartphone MAC Address Randomization**: Mobile devices with MAC randomization enabled generate dynamic MAC addresses when re-connecting. It is recommended to disable MAC randomization for your home Wi-Fi network on iOS and Android for reliable presence tracking.

## Troubleshooting

### Authentication Errors

If the router admin password changes, Home Assistant will prompt a **Re-authentication** flow. Navigate to **Settings** > **Devices & Services** > **GL-iNet** and enter your updated password.

### SSL Certificate Failures

If connecting via `https://` with a self-signed certificate, ensure **Verify SSL certificate** is disabled in the integration configuration or options menu.

### Diagnostic Logs

To collect detailed troubleshooting logs, enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.glinet: debug
    gli4py: debug
```
