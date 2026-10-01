"""WAN status helpers for the GL-iNet integration.

Pure helpers (state mapping, friendly names, malformed-input parsing) live
here so they can be unit-tested without a Home Assistant harness. The
WanStatusSensor entity class lives in sensor.
"""

from __future__ import annotations

from dataclasses import dataclass

STATE_CONNECTED = "connected"
STATE_FAILING = "failing"
STATE_DISCONNECTED = "disconnected"


def state_for(*, up: bool, online: bool) -> str:
    """Map link/internet booleans to one of the three WAN states."""
    if not up:
        return STATE_DISCONNECTED
    if not online:
        return STATE_FAILING
    return STATE_CONNECTED


_FRIENDLY_NAMES: dict[str, str] = {
    "wan": "Primary WAN",
    "secondwan": "Secondary WAN",
    "wan6": "Primary WAN (IPv6)",
    "secondwan6": "Secondary WAN (IPv6)",
    "wwan": "WiFi Repeater",
    "wwan6": "WiFi Repeater (IPv6)",
    "tethering": "Phone Tether",
    "tethering6": "Phone Tether (IPv6)",
}


def friendly_name(interface: str) -> str:
    """Return a UI-friendly label for a raw GL-iNet interface name.

    Multiple USB modems get the raw suffix appended in parentheses so a
    user with two modems sees two distinct entity names.
    """
    if interface in _FRIENDLY_NAMES:
        return _FRIENDLY_NAMES[interface]
    if interface.startswith("modem_"):
        if interface.endswith("_6"):
            return f"USB Modem IPv6 ({interface})"
        return f"USB Modem ({interface})"
    return interface


@dataclass(frozen=True)
class WanInterfaceState:
    """Latest known state of one WAN interface, as reported by the router."""

    name: str
    up: bool
    online: bool
