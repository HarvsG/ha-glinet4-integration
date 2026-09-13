"""Unit tests for the WAN helpers and sensors."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import MOCK_MAC


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
    """state_for covers every (up, online) combination."""
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
    """Parses standard network array payload."""
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
    """The failing state is preserved through parsing."""
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
    """Entry with no name is silently dropped."""
    raw = [
        {"interface": "wan", "up": True, "online": True},
        {"online": False, "up": False},
        {"interface": "", "up": True, "online": True},
        {"interface": 42, "up": True, "online": True},
    ]
    result = parse_network_array(raw)
    assert set(result.states.keys()) == {"wan"}
    assert result.malformed_interfaces == []


def test_parse_network_array_defaults_missing_bools_and_warns() -> None:
    """Entry has a name but missing up/online."""
    raw = [
        {"interface": "wan", "up": True, "online": True},
        {"interface": "secondwan"},
        {"interface": "wan6", "up": True},
    ]
    result = parse_network_array(raw)
    assert result.states["secondwan"].up is False
    assert result.states["secondwan"].online is False
    assert result.states["wan6"].up is True
    assert result.states["wan6"].online is False
    assert sorted(result.malformed_interfaces) == ["secondwan", "wan6"]


def test_parse_network_array_coerces_truthy_non_bool() -> None:
    """Handle integer 0/1 values for bool flags."""
    raw = [{"interface": "wan", "up": 1, "online": 0}]
    result = parse_network_array(raw)
    assert result.states["wan"].up is True
    assert result.states["wan"].online is False


async def test_wan_sensor_integration(
    hass: HomeAssistant, mock_api: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test WAN sensors registration and state updates."""
    router = init_integration.runtime_data
    assert router is not None

    # Update router network status with active WAN interfaces
    mock_status = {
        "system": {"uptime": 1000},
        "network": [
            {"interface": "wan", "up": True, "online": True},
            {"interface": "secondwan", "up": True, "online": False},
        ],
    }
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = mock_status

    await router.update_system_status()
    await hass.async_block_till_done()

    entity_reg = er.async_get(hass)
    wan_entity_id = entity_reg.async_get_entity_id(
        "sensor", DOMAIN, f"glinet_sensor/{MOCK_MAC}/wan_wan"
    )
    assert wan_entity_id is not None
    state = hass.states.get(wan_entity_id)
    assert state is not None
    assert state.state == STATE_CONNECTED
    assert state.attributes.get("interface") == "wan"
    assert state.attributes.get("up") is True

    second_wan_id = entity_reg.async_get_entity_id(
        "sensor", DOMAIN, f"glinet_sensor/{MOCK_MAC}/wan_secondwan"
    )
    assert second_wan_id is not None
    state = hass.states.get(second_wan_id)
    assert state is not None
    assert state.state == STATE_FAILING
