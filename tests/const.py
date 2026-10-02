"""Canned GL-iNet API data shared by the tests."""

from __future__ import annotations

from typing import Any

from gli4py.models import (
    ClientEntry,
    RouterStatusResponse,
    TailscaleConfigResponse,
    WifiInterface,
    WireguardClientListItem,
    WireguardStatusItem,
)

MOCK_MAC = "94:83:C4:11:22:33"
# DHCP discovery reports the LAN MAC (factory MAC + 1) without separators
MOCK_LAN_MAC = "9483c4112234"
MOCK_HOST = "http://192.168.8.1"

MOCK_ROUTER_INFO: dict[str, Any] = {
    "model": "b1300",
    "firmware_version": "4.3.25",
    "mac": MOCK_MAC,
}

_MOCK_STATUS_RAW: dict[str, Any] = {
    "system": {
        "uptime": 86400.0,
        "load_average": [0.15, 0.2, 0.18],
        "memory_total": 254586880,
        "memory_free": 137543680,
        "memory_buff_cache": 33550336,  # -> memory usage ~32.80%
        "flash_total": 33554432,
        "flash_free": 14135296,  # -> flash usage ~57.87%
    }
}
MOCK_STATUS: RouterStatusResponse = RouterStatusResponse.from_dict(_MOCK_STATUS_RAW)

_MOCK_CLIENTS_RAW: dict[str, dict[str, Any]] = {
    "B8:27:EB:44:55:66": {
        "alias": "HomeAssistant-Yellow",
        "name": "homeassistant",
        "ip": "192.168.1.10",
        "online": True,
        "type": 2,
    },
    "00:1E:67:A1:B2:C3": {
        "alias": "Proxmox-Node-01",
        "name": "pve",
        "ip": "192.168.1.20",
        "online": True,
        "type": 2,
    },
    "E8:DB:84:77:88:99": {
        "alias": "Shelly-LivingRoom-Main",
        "name": "shelly1-A4B5C6",
        "ip": "192.168.1.30",
        "online": True,
        "type": 0,
    },
    "24:6F:28:11:22:33": {
        "alias": "ESP32-Bluetooth-Proxy-Hallway",
        "name": "esphome-bt-proxy",
        "ip": "192.168.1.50",
        "online": True,
        "type": 0,
    },
}
MOCK_CLIENTS: dict[str, ClientEntry] = {
    mac: ClientEntry.from_dict({"mac": mac, **data})
    for mac, data in _MOCK_CLIENTS_RAW.items()
}

_MOCK_WIFI_IFACES_RAW: dict[str, dict[str, Any]] = {
    "default_radio0": {
        "enabled": True,
        "ssid": "GL-MOCK-2G",
        "guest": False,
        "hidden": False,
        "encryption": "psk2",
    },
    "guest2g": {
        "enabled": False,
        "ssid": "GL-MOCK-2G-Guest",
        "guest": True,
        "hidden": False,
        "encryption": "psk2",
    },
    "default_radio1": {
        "enabled": True,
        "ssid": "GL-MOCK-5G",
        "guest": False,
        "hidden": False,
        "encryption": "sae-mixed",
    },
    "guest5g": {
        "enabled": False,
        "ssid": "GL-MOCK-5G-Guest",
        "guest": True,
        "hidden": False,
        "encryption": "psk2",
    },
}
MOCK_WIFI_IFACES: dict[str, WifiInterface] = {
    name: WifiInterface.from_dict({"name": name, **data})
    for name, data in _MOCK_WIFI_IFACES_RAW.items()
}

_MOCK_WG_CLIENTS_RAW: list[dict[str, Any]] = [
    {"name": "MockVPN/MockTunnel", "group_id": 7707, "peer_id": 2001},
    {"name": "MockVPN/MockSplitTunnel", "group_id": 7707, "peer_id": 2002},
]
MOCK_WG_CLIENTS: list[WireguardClientListItem] = [
    WireguardClientListItem.from_dict(item) for item in _MOCK_WG_CLIENTS_RAW
]

_MOCK_WG_STATE_RAW: list[dict[str, Any]] = [
    {
        "domain": "vpn.mock.example.com",
        "enabled": False,
        "group_id": 1001,
        "ipv4": "10.0.0.2",
        "ipv6": "",
        "name": "MockWGGroup/Peer1",
        "peer_id": 2001,
        "port": 51820,
        "proxy": True,
        "rx_bytes": 0,
        "status": 0,
        "tunnel_id": 2001,
        "tx_bytes": 0,
    }
]
MOCK_WG_STATE: list[WireguardStatusItem] = [
    WireguardStatusItem.from_dict(item) for item in _MOCK_WG_STATE_RAW
]

_MOCK_TAILSCALE_CONFIG_RAW: dict[str, Any] = {
    "enabled": False,
    "lan_enabled": True,
    "lan_ip": "192.168.8.0/24",
    "wan_enabled": False,
}
MOCK_TAILSCALE_CONFIG: TailscaleConfigResponse = TailscaleConfigResponse.from_dict(
    _MOCK_TAILSCALE_CONFIG_RAW
)

# Everything polled each cycle: four methods by the router's own interval
# plus tailscale_configured and led_get_config via the Tailscale and LED switch
# entities' async_update. A single succeeding call clears the connect-error
# latch, so unavailability tests must fail them all.
POLLED_METHODS = (
    "router_get_status",
    "all_clients",
    "wifi_ifaces_get",
    "wireguard_client_list",
    "wireguard_client_state",
    "tailscale_configured",
    "tailscale_connection_state",
    "led_get_config",
)
