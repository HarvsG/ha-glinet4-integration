"""Tests for the GL-iNet switches."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock, call

from freezegun.api import FrozenDateTimeFactory
from gli4py.enums import TailscaleConnection
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import MOCK_MAC, MOCK_WIFI_IFACES, POLLED_METHODS

WG_CLIENTS_OLD_FIRMWARE = [
    {"name": "wg_home", "peer_id": 1, "group_id": 10},
    {"name": "wg_office", "peer_id": 2, "group_id": 10},
]

WG_STATE_OLD_FIRMWARE = [
    {"type": "wireguard", "peer_id": 1, "status": 1},
    {"type": "wireguard", "peer_id": 2, "status": 0},
]


def _entity_id(hass: HomeAssistant, unique_suffix: str) -> str:
    """Resolve a switch entity id from its unique id suffix."""
    registry = er.async_get(hass)
    unique_id = f"glinet_switch/{MOCK_MAC}/{unique_suffix}"
    entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_wifi_switch_state_and_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the WiFi AP switches mirror the interface states."""
    state = hass.states.get(_entity_id(hass, "iface_wlan0"))
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["interface"] == "wlan0"
    assert state.attributes["ssid"] == "MyWifi"
    assert state.attributes["guest"] is False
    assert state.attributes["hidden"] is False
    assert state.attributes["encryption"] == "sae"

    state = hass.states.get(_entity_id(hass, "iface_wlan1"))
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["guest"] is True


async def test_wifi_switch_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test toggling a WiFi AP calls the API and updates the state."""
    entity_id = _entity_id(hass, "iface_wlan0")

    ifaces = deepcopy(MOCK_WIFI_IFACES)
    ifaces["wlan0"]["enabled"] = False
    mock_api.wifi_ifaces_get.side_effect = lambda *_a, **_kw: deepcopy(ifaces)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wifi_iface_set_enabled.assert_awaited_with("wlan0", False)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    ifaces["wlan0"]["enabled"] = True
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wifi_iface_set_enabled.assert_awaited_with("wlan0", True)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


async def test_tailscale_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test the Tailscale switch reflects and controls the connection."""
    entity_id = _entity_id(hass, "tailscale")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON

    # Polled entities are force-refreshed after a service call, so the
    # mocked router must report the new connection state
    mock_api.tailscale_connection_state.return_value = TailscaleConnection.DISCONNECTED
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.tailscale_stop.assert_awaited_once()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    mock_api.tailscale_connection_state.return_value = TailscaleConnection.CONNECTED
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.tailscale_start.assert_awaited_once()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


async def test_wireguard_switch_states(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the WireGuard switches mirror the client connection states."""
    state = hass.states.get(_entity_id(hass, "wg_home/wireguard_client"))
    assert state is not None
    assert state.state == STATE_ON

    state = hass.states.get(_entity_id(hass, "wg_office/wireguard_client"))
    assert state is not None
    assert state.state == STATE_OFF


async def test_wireguard_switch_turn_on_modern_firmware(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test turning on a client with a tunnel id does not stop other clients."""
    entity_id = _entity_id(hass, "wg_office/wireguard_client")

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wireguard_client_start.assert_awaited_once_with(10, 200)
    mock_api.wireguard_client_stop.assert_not_awaited()


async def test_wireguard_switch_turn_on_older_firmware_stops_others(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test older firmware clients stop connected clients before starting."""
    mock_api.wireguard_client_list.side_effect = lambda *_a, **_kw: deepcopy(
        WG_CLIENTS_OLD_FIRMWARE
    )
    mock_api.wireguard_client_state.side_effect = lambda *_a, **_kw: deepcopy(
        WG_STATE_OLD_FIRMWARE
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    manager = MagicMock()
    manager.attach_mock(mock_api.wireguard_client_stop, "stop")
    manager.attach_mock(mock_api.wireguard_client_start, "start")

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: _entity_id(hass, "wg_office/wireguard_client")},
        blocking=True,
    )
    # The connected wg_home client (peer 1) is stopped before wg_office
    # (group 10, peer 2) is started
    assert manager.mock_calls == [call.stop(1), call.start(10, 2)]


async def test_wireguard_switch_turn_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test turning off a WireGuard client stops it by tunnel id."""
    entity_id = _entity_id(hass, "wg_home/wireguard_client")

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wireguard_client_stop.assert_awaited_once_with(100)


async def test_switch_unavailable_on_connect_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test switches become unavailable when the router is unreachable."""
    entity_id = _entity_id(hass, "iface_wlan0")

    for name in POLLED_METHODS:
        getattr(mock_api, name).side_effect = TimeoutError
    # Two ticks: one for the router to latch the error, one for the entity
    # poll to pick it up (both run on the same clock)
    for _ in range(2):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
