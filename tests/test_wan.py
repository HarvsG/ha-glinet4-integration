"""Unit tests for the WAN helpers and sensors."""

from __future__ import annotations

from unittest.mock import MagicMock

from gli4py.models import RouterStatusResponse, SystemStatusMetrics, SystemStatusNetwork
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.wan import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_FAILING,
    friendly_name,
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


async def test_wan_sensor_integration(
    hass: HomeAssistant, mock_api: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test WAN sensors registration and state updates."""
    router = init_integration.runtime_data.router
    assert router is not None

    # Update router network status with active WAN interfaces
    mock_status = RouterStatusResponse(
        system=SystemStatusMetrics(uptime=1000),
        network=[
            SystemStatusNetwork(interface="wan", up=True, online=True),
            SystemStatusNetwork(interface="secondwan", up=True, online=False),
        ],
    )
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = mock_status

    coordinator = init_integration.runtime_data.coordinator
    await coordinator.async_refresh()
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
