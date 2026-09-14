"""Canned GL-iNet API data shared by the tests."""

from __future__ import annotations

MOCK_MAC = "94:83:c4:aa:bb:cc"
# DHCP discovery reports the LAN MAC (factory MAC + 1) without separators
MOCK_LAN_MAC = "9483c4aabbcd"
MOCK_HOST = "http://192.168.8.1"

MOCK_ROUTER_INFO = {
    "model": "mt6000",
    "firmware_version": "4.8.2",
    "mac": MOCK_MAC,
}

MOCK_STATUS = {
    "system": {
        "cpu": {"temperature": 42.5},
        "load_average": [0.25, 0.5, 1.0],
        "memory_total": 1_024_000,
        "memory_free": 256_000,  # -> memory usage 75.0 %
        "flash_total": 100_000,
        "flash_free": 90_000,  # -> flash usage 10.0 %
        "uptime": 3600.0,
    }
}

MOCK_CLIENTS = {
    "aa:bb:cc:dd:ee:01": {
        "alias": "Phone",
        "name": "phone",
        "ip": "192.168.8.100",
        "online": True,
        "type": 1,
    },
    "aa:bb:cc:dd:ee:02": {
        "alias": "",
        "name": "laptop",
        "ip": "192.168.8.101",
        "online": True,
        "type": 2,
    },
}

MOCK_WIFI_IFACES = {
    "wlan0": {
        "enabled": True,
        "ssid": "MyWifi",
        "guest": False,
        "hidden": False,
        "encryption": "sae",
    },
    "wlan1": {
        "enabled": False,
        "ssid": "GuestWifi",
        "guest": True,
        "hidden": True,
        "encryption": "psk2",
    },
}

MOCK_WG_CLIENTS = [
    {"name": "wg_home", "peer_id": 1, "group_id": 10, "tunnel_id": 100},
    {"name": "wg_office", "peer_id": 2, "group_id": 10, "tunnel_id": 200},
]

MOCK_WG_STATE = [
    {"type": "wireguard", "peer_id": 1, "status": 1, "tunnel_id": 100},
    {"type": "wireguard", "peer_id": 2, "status": 0, "tunnel_id": 200},
]

MOCK_TAILSCALE_CONFIG = {"lan_enabled": True}

# Everything polled each cycle: four methods by the router's own interval
# plus tailscale_configured via the Tailscale switch entity's async_update.
# A single succeeding call clears the connect-error latch, so unavailability
# tests must fail them all.
POLLED_METHODS = (
    "router_get_status",
    "connected_clients",
    "wifi_ifaces_get",
    "wireguard_client_list",
    "tailscale_configured",
)
