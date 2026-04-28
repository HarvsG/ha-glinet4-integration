"""Unit tests for the WAN helpers."""

from __future__ import annotations

import pytest

from custom_components.glinet.wan import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_FAILING,
    ParseResult,
    WanInterfaceState,
    friendly_name,
    parse_network_array,
    state_for,
)


@pytest.mark.parametrize(
    ("up", "online", "expected"),
    [
        (True, True, STATE_CONNECTED),
        (True, False, STATE_FAILING),
        (False, True, STATE_DISCONNECTED),
        (False, False, STATE_DISCONNECTED),
    ],
)
def test_state_for_all_combinations(up: bool, online: bool, expected: str) -> None:
    """`state_for` covers every (up, online) combination."""
    assert state_for(up=up, online=online) == expected


@pytest.mark.parametrize(
    ("interface", "expected"),
    [
        ("wan", "Primary WAN"),
        ("secondwan", "Secondary WAN"),
        ("wan6", "Primary WAN (IPv6)"),
        ("secondwan6", "Secondary WAN (IPv6)"),
        ("wwan", "WiFi Repeater"),
        ("wwan6", "WiFi Repeater (IPv6)"),
        ("tethering", "Phone Tether"),
        ("tethering6", "Phone Tether (IPv6)"),
        ("modem_1_1_2", "USB Modem (modem_1_1_2)"),
        ("modem_1_1_2_6", "USB Modem IPv6 (modem_1_1_2_6)"),
        ("modem_2_3", "USB Modem (modem_2_3)"),
        ("future_unknown_iface", "future_unknown_iface"),
        ("", ""),
    ],
)
def test_friendly_name(interface: str, expected: str) -> None:
    """Documented mappings + modem disambiguation + raw passthrough."""
    assert friendly_name(interface) == expected


def test_parse_network_array_happy_path() -> None:
    """Parses the realistic BE9300 payload."""
    raw = [
        {"interface": "wan", "online": True, "up": True},
        {"interface": "secondwan", "online": True, "up": True},
        {"interface": "wan6", "online": False, "up": False},
    ]
    result = parse_network_array(raw)
    assert result.malformed_interfaces == []
    assert result.states == {
        "wan": WanInterfaceState(name="wan", up=True, online=True),
        "secondwan": WanInterfaceState(name="secondwan", up=True, online=True),
        "wan6": WanInterfaceState(name="wan6", up=False, online=False),
    }


def test_parse_network_array_link_up_no_internet() -> None:
    """The 'failing' state is preserved through parsing."""
    raw = [{"interface": "wan", "online": False, "up": True}]
    result = parse_network_array(raw)
    assert result.states["wan"].up is True
    assert result.states["wan"].online is False


def test_parse_network_array_non_list_returns_empty() -> None:
    """Garbage input is dropped, not exceptions."""
    for raw in (None, {}, "wan", 42):
        result = parse_network_array(raw)
        assert result.states == {}
        assert isinstance(result, ParseResult)


def test_parse_network_array_skips_non_dict_entries() -> None:
    """Non-dict items in the list are silently dropped."""
    raw = [None, "wan", 42, {"interface": "wan", "up": True, "online": True}]
    result = parse_network_array(raw)
    assert set(result.states.keys()) == {"wan"}


def test_parse_network_array_skips_entries_without_interface_name() -> None:
    """Entry with no name is silently dropped (no name to warn about)."""
    raw = [
        {"interface": "wan", "up": True, "online": True},
        {"online": False, "up": False},  # no interface key
        {"interface": "", "up": True, "online": True},  # empty name
        {"interface": 42, "up": True, "online": True},  # non-string
    ]
    result = parse_network_array(raw)
    assert set(result.states.keys()) == {"wan"}
    assert result.malformed_interfaces == []


def test_parse_network_array_defaults_missing_bools_and_warns() -> None:
    """Entry has a name but missing up/online — defaults to False, flag for warning."""
    raw = [
        {"interface": "wan", "up": True, "online": True},
        {"interface": "secondwan"},  # missing both
        {"interface": "wan6", "up": True},  # missing online
    ]
    result = parse_network_array(raw)
    assert result.states["secondwan"].up is False
    assert result.states["secondwan"].online is False
    assert result.states["wan6"].up is True
    assert result.states["wan6"].online is False
    assert sorted(result.malformed_interfaces) == ["secondwan", "wan6"]


def test_parse_network_array_coerces_truthy_non_bool() -> None:
    """Some firmware versions might return 0/1 ints instead of bools."""
    raw = [{"interface": "wan", "up": 1, "online": 0}]
    result = parse_network_array(raw)
    assert result.states["wan"].up is True
    assert result.states["wan"].online is False
