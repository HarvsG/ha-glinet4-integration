"""Tests for the client interface-type resolver."""

from __future__ import annotations

import pytest

from custom_components.glinet.models import (
    DeviceInterfaceType,
    interface_type_from_client,
)


@pytest.mark.parametrize(
    ("iface", "expected"),
    [
        ("2.4G", DeviceInterfaceType.WIFI_24),
        ("5G", DeviceInterfaceType.WIFI_5),
        ("6G", DeviceInterfaceType.WIFI_6),
        ("MLO", DeviceInterfaceType.MLO),
        ("mlo", DeviceInterfaceType.MLO),
        ("cable", DeviceInterfaceType.LAN),
        ("wired", DeviceInterfaceType.LAN),
        ("2.4G Guest", DeviceInterfaceType.WIFI_24_GUEST),
        ("5G Guest", DeviceInterfaceType.WIFI_5_GUEST),
        ("6G Guest", DeviceInterfaceType.WIFI_6_GUEST),
        ("MLO Guest", DeviceInterfaceType.MLO_GUEST),
    ],
)
def test_resolves_from_iface_string(iface: str, expected: DeviceInterfaceType) -> None:
    """The self-describing iface string is resolved case-insensitively."""
    assert interface_type_from_client({"iface": iface}) is expected


def test_iface_wins_over_out_of_range_type() -> None:
    """A valid iface resolves even when the integer type is out of range."""
    result = interface_type_from_client({"iface": "MLO", "type": 14})
    assert result is DeviceInterfaceType.MLO


@pytest.mark.parametrize(
    ("type_code", "expected"),
    [
        (0, DeviceInterfaceType.WIFI_24),
        (1, DeviceInterfaceType.WIFI_5),
        (2, DeviceInterfaceType.LAN),
        (9, DeviceInterfaceType.MLO),
        (11, DeviceInterfaceType.WIFI_6),
        ("1", DeviceInterfaceType.WIFI_5),
    ],
)
def test_falls_back_to_type_code(
    type_code: object, expected: DeviceInterfaceType
) -> None:
    """With no usable iface, the legacy integer type code is used."""
    assert interface_type_from_client({"type": type_code}) is expected


@pytest.mark.parametrize("type_code", [14, 99, -1, "x", None, True])
def test_unrecognised_resolves_to_unknown_without_raising(type_code: object) -> None:
    """Out-of-range / non-numeric / missing codes resolve to UNKNOWN, never raise."""
    assert (
        interface_type_from_client({"type": type_code}) is DeviceInterfaceType.UNKNOWN
    )


def test_empty_dev_info_is_unknown() -> None:
    """A client with neither iface nor type resolves to UNKNOWN."""
    assert interface_type_from_client({}) is DeviceInterfaceType.UNKNOWN


def test_no_duplicate_unknown_member() -> None:
    """The enum has a single Unknown member (the old duplicate was the foot-gun)."""
    unknowns = [m for m in DeviceInterfaceType if m.value == "Unknown"]
    assert unknowns == [DeviceInterfaceType.UNKNOWN]
