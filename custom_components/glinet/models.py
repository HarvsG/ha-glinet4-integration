"""Data models shared across the GL-iNet integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from functools import cache
import logging

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class DeviceInterfaceType(StrEnum):
    """The interface a client is connected to the router through."""

    WIFI_24 = "2.4GHz"
    WIFI_5 = "5GHz"
    WIFI_6 = "6GHz"
    WIFI_24_GUEST = "2.4GHz Guest"
    WIFI_5_GUEST = "5GHz Guest"
    WIFI_6_GUEST = "6GHz Guest"
    MLO = "MLO"
    MLO_GUEST = "MLO Guest"
    LAN = "LAN"
    DONGLE = "Dongle"
    BYPASS_ROUTE = "Bypass Route"
    UNKNOWN = "Unknown"


# Maps the self-describing ``iface`` string the router reports per client to a
# DeviceInterfaceType (lower-cased for case-insensitive matching). Resolving from
# this first makes interface labelling resilient to firmware that renumbers the
# integer ``type`` codes.
_IFACE_MAP: dict[str, DeviceInterfaceType] = {
    "2.4g": DeviceInterfaceType.WIFI_24,
    "5g": DeviceInterfaceType.WIFI_5,
    "6g": DeviceInterfaceType.WIFI_6,
    "mlo": DeviceInterfaceType.MLO,
    "cable": DeviceInterfaceType.LAN,
    "wired": DeviceInterfaceType.LAN,
    "lan": DeviceInterfaceType.LAN,
}

# Guest networks carry a "guest" qualifier on some firmware; the first matching
# band token wins. "2.4" is checked before "5"/"6" so it isn't shadowed.
_GUEST_TOKENS: tuple[tuple[str, DeviceInterfaceType], ...] = (
    ("2.4", DeviceInterfaceType.WIFI_24_GUEST),
    ("6", DeviceInterfaceType.WIFI_6_GUEST),
    ("mlo", DeviceInterfaceType.MLO_GUEST),
    ("5", DeviceInterfaceType.WIFI_5_GUEST),
)

# Fallback mapping from the legacy integer ``type`` code. Positions matter:
# indices 5 and 8 are reserved/unknown slots on observed firmware. An explicit
# tuple (not ``list(DeviceInterfaceType)``) keeps the mapping stable and
# bounds-safe - the unbounded enum index previously crashed with an IndexError
# on Wi-Fi 7 / MLO clients.
_TYPE_INDEX: tuple[DeviceInterfaceType, ...] = (
    DeviceInterfaceType.WIFI_24,  # 0
    DeviceInterfaceType.WIFI_5,  # 1
    DeviceInterfaceType.LAN,  # 2
    DeviceInterfaceType.WIFI_24_GUEST,  # 3
    DeviceInterfaceType.WIFI_5_GUEST,  # 4
    DeviceInterfaceType.UNKNOWN,  # 5 (reserved)
    DeviceInterfaceType.DONGLE,  # 6
    DeviceInterfaceType.BYPASS_ROUTE,  # 7
    DeviceInterfaceType.UNKNOWN,  # 8 (reserved)
    DeviceInterfaceType.MLO,  # 9
    DeviceInterfaceType.MLO_GUEST,  # 10
    DeviceInterfaceType.WIFI_6,  # 11
    DeviceInterfaceType.WIFI_6_GUEST,  # 12
)


def _interface_type_from_code(raw_type: object) -> DeviceInterfaceType:
    """Resolve the legacy integer ``type`` code to an interface, never raising."""
    index: int | None = None
    if isinstance(raw_type, bool):
        index = None  # bool is an int subclass but is never a real type code
    elif isinstance(raw_type, int):
        index = raw_type
    elif isinstance(raw_type, str):
        try:
            index = int(raw_type)
        except ValueError:
            index = None
    if index is not None and 0 <= index < len(_TYPE_INDEX):
        return _TYPE_INDEX[index]
    return DeviceInterfaceType.UNKNOWN


@cache
def _log_unrecognised_interface(
    iface: str,
    raw_type: str,
    model: str,
    firmware: str,
    dev_info_fields: tuple[str, ...],
) -> None:
    """Warn once per distinct context so an unknown interface doesn't spam logs."""
    _LOGGER.warning(
        "Unrecognised device interface (iface=%s type=%s) on GL-iNet model %s "
        "(firmware %s; dev_info fields=%s). Using Unknown - please open an issue "
        "with this log so support can be added",
        iface or "<none>",
        raw_type,
        model or "unknown",
        firmware or "unknown",
        dev_info_fields,
    )


def interface_type_from_client(
    dev_info: dict, *, model: str = "", firmware: str = ""
) -> DeviceInterfaceType:
    """Best-effort interface resolution from a client's dev_info, never raising.

    Prefers the human-readable ``iface`` string ("2.4G", "5G", "6G", "MLO",
    "cable"), falling back to the legacy integer ``type`` code. Unrecognised
    interfaces resolve to UNKNOWN (logged once) so a device is always tracked,
    never dropped, regardless of how it is connected.
    """
    iface = str(dev_info.get("iface") or "").strip().lower()
    if iface in _IFACE_MAP:
        return _IFACE_MAP[iface]
    if "guest" in iface:
        for token, guest_type in _GUEST_TOKENS:
            if token in iface:
                return guest_type
    if "mlo" in iface:
        return DeviceInterfaceType.MLO

    resolved = _interface_type_from_code(dev_info.get("type"))
    if resolved is DeviceInterfaceType.UNKNOWN and (
        dev_info.get("iface") or dev_info.get("type") is not None
    ):
        _log_unrecognised_interface(
            iface,
            str(dev_info.get("type")),
            model,
            firmware,
            tuple(sorted(str(key) for key in dev_info)),
        )
    return resolved


@dataclass
class WireGuardClient:
    """Class for keeping track of WireGuard Client Configs."""

    name: str
    connected: bool = field(compare=False)
    group_id: int
    peer_id: int
    tunnel_id: int | None


@dataclass
class WifiInterface:
    """Class for keeping track of Wifi Interfaces."""

    name: str
    enabled: bool
    ssid: str
    guest: bool
    hidden: bool
    encryption: str


class ClientDevInfo:
    """Representation of a device connected to the router."""

    def __init__(self, mac: str, name: str | None = None) -> None:
        """Initialize a connected device."""
        self._mac: str = mac
        self._name: str | None = name
        self._ip_address: str | None = None
        self._last_activity: datetime = dt_util.utcnow() - timedelta(days=1)
        self._connected: bool = False
        self._if_type: DeviceInterfaceType = DeviceInterfaceType.UNKNOWN

    def update(
        self,
        dev_info: dict | None = None,
        consider_home: int = 0,
        *,
        model: str = "",
        firmware: str = "",
    ) -> None:
        """Update connected device info."""
        now: datetime = dt_util.utcnow()
        if dev_info:
            # Prefer the user-defined alias as a name
            alias = dev_info.get("alias")
            if alias and alias.strip():
                self._name = alias
            else:
                # If no alias, fallback to auto-assigned name field
                name = dev_info.get("name", "")
                if name == "*" or not name.strip():
                    self._name = self._mac.replace(":", "_")
                else:
                    self._name = name
            self._ip_address = dev_info.get("ip")
            self._last_activity = now
            self._connected = dev_info.get("online", False)
            self._if_type = interface_type_from_client(
                dev_info, model=model, firmware=firmware
            )
        # a device might not actually be online but we want to consider it home
        elif self._connected:
            self._connected = (
                now - self._last_activity
            ).total_seconds() < consider_home
            self._ip_address = None

    @property
    def is_connected(self) -> bool:
        """Return connected status."""
        return self._connected

    @property
    def interface_type(self) -> DeviceInterfaceType:
        """Return device interface type."""
        return self._if_type

    @property
    def mac(self) -> str:
        """Return device mac address."""
        return self._mac

    @property
    def name(self) -> str | None:
        """Return device name."""
        return self._name

    @property
    def ip_address(self) -> str | None:
        """Return device ip address."""
        return self._ip_address

    @property
    def last_activity(self) -> datetime:
        """Return device last activity."""
        return self._last_activity
