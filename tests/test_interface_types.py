"""Tests for client interface type resolution."""

from __future__ import annotations

import pytest

from custom_components.glinet.router import ClientDevInfo, DeviceInterfaceType


@pytest.mark.parametrize(
    ("iface", "type_index", "expected"),
    [
        ("2.4G", 11, DeviceInterfaceType.WIFI_24),
        ("5G", 11, DeviceInterfaceType.WIFI_5),
        ("6G", 1, DeviceInterfaceType.WIFI_6),
        ("MLO", 1, DeviceInterfaceType.MLO),
        ("cable", 11, DeviceInterfaceType.LAN),
        ("5G Guest", 1, DeviceInterfaceType.WIFI_5_GUEST),
        ("6G Guest", 1, DeviceInterfaceType.WIFI_6_GUEST),
        ("MLO Guest", 1, DeviceInterfaceType.MLO_GUEST),
    ],
)
def test_iface_is_preferred_over_numeric_type(
    iface: str, type_index: int, expected: DeviceInterfaceType
) -> None:
    """The self-describing iface value should take precedence over type."""
    device = ClientDevInfo("aa:bb:cc:dd:ee:ff")
    device.update(
        {
            "name": "dev",
            "ip": "192.168.8.2",
            "iface": iface,
            "type": type_index,
        }
    )
    assert device.interface_type is expected


@pytest.mark.parametrize(
    ("type_value", "expected"),
    [
        (11, DeviceInterfaceType.WIFI_6),
        ("12", DeviceInterfaceType.WIFI_6_GUEST),
        (99, DeviceInterfaceType.UNKNOWN),
        ("invalid", DeviceInterfaceType.UNKNOWN),
        (True, DeviceInterfaceType.UNKNOWN),
    ],
)
def test_numeric_type_fallback(
    type_value: object, expected: DeviceInterfaceType
) -> None:
    """Fall back safely to the legacy numeric type when iface is unavailable."""
    device = ClientDevInfo("aa:bb:cc:dd:ee:ff")
    device.update(
        {
            "name": "dev",
            "ip": "192.168.8.2",
            "iface": "unknown-interface",
            "type": type_value,
        }
    )
    assert device.interface_type is expected
