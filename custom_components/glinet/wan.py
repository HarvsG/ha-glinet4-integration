"""WAN status helpers for the GL-iNet integration.

Pure helpers (state mapping, friendly names, malformed-input parsing) live
here so they can be unit-tested without a Home Assistant harness. The
``WanStatusSensor`` entity class lives in :mod:`wan_sensor`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class ParseResult:
    """Output of :func:`parse_network_array`.

    ``malformed_interfaces`` is the list of interface names whose entry was
    missing one or both of the ``up`` / ``online`` fields. Callers should
    log a one-time warning for each such name.
    """

    states: dict[str, WanInterfaceState]
    malformed_interfaces: list[str] = field(default_factory=list)


def parse_network_array(raw: object) -> ParseResult:
    """Parse the ``network`` field of ``router_get_status`` into a state map.

    Pure function — no logging, no side effects. Caller is responsible for
    logging warnings about ``malformed_interfaces``.

    Behaviour:
    - Non-list input → empty result.
    - Entries that are not dicts → silently dropped.
    - Entries missing a non-empty string ``interface`` → silently dropped.
    - Entries with a name but missing ``up`` / ``online`` → recorded, the
      missing field defaults to ``False``, and the name is added to
      ``malformed_interfaces`` so the caller can warn once.
    """
    if not isinstance(raw, list):
        return ParseResult(states={})

    states: dict[str, WanInterfaceState] = {}
    malformed: list[str] = []

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("interface")
        if not isinstance(name, str) or not name:
            continue
        has_up = "up" in entry
        has_online = "online" in entry
        if not (has_up and has_online):
            malformed.append(name)
        states[name] = WanInterfaceState(
            name=name,
            up=bool(entry.get("up", False)),
            online=bool(entry.get("online", False)),
        )

    return ParseResult(states=states, malformed_interfaces=malformed)
