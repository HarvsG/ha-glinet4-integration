"""Tests for the GL-iNet switches."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import cast
from unittest.mock import MagicMock, call

from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import NonZeroResponse
from gli4py.models import TailscaleConnection
from gli4py.types import TailscaleConfigResponse
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.switch import TailscaleSwitch
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

from .const import MOCK_MAC, POLLED_METHODS

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
    state = hass.states.get(_entity_id(hass, "iface_default_radio0"))
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["interface"] == "default_radio0"
    assert state.attributes["ssid"] == "GL-MOCK-2G"
    assert state.attributes["guest"] is False
    assert state.attributes["hidden"] is False
    assert state.attributes["encryption"] == "psk2"

    state = hass.states.get(_entity_id(hass, "iface_guest2g"))
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["guest"] is True


async def test_wifi_switch_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test toggling a WiFi AP calls the API and updates the state."""
    entity_id = _entity_id(hass, "iface_default_radio0")

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wifi_iface_set_enabled.assert_awaited_with("default_radio0", False)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wifi_iface_set_enabled.assert_awaited_with("default_radio0", True)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


async def test_tailscale_switch(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the Tailscale switch reflects and controls the connection."""
    entity_id = _entity_id(hass, "tailscale")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes.get("lan_access") is True

    # Polled entities are force-refreshed after a service call, so the
    # mocked router must report the new connection state
    mock_api.tailscale_connection_state.return_value = TailscaleConnection.DISCONNECTED
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert mock_api.tailscale_stop.await_count >= 1
    assert "Disabling tailscale" in caplog.text
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    caplog.clear()
    mock_api.tailscale_connection_state.return_value = TailscaleConnection.CONNECTED
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert mock_api.tailscale_start.await_count >= 1
    assert "Enabling tailscale" in caplog.text
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


async def test_wireguard_switch_states(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the WireGuard switches mirror the client connection states."""
    state = hass.states.get(_entity_id(hass, "MockVPN/MockTunnel/wireguard_client"))
    assert state is not None
    assert state.state == STATE_OFF

    state = hass.states.get(
        _entity_id(hass, "MockVPN/MockSplitTunnel/wireguard_client")
    )
    assert state is not None
    assert state.state == STATE_OFF


async def test_wireguard_switch_turn_on_modern_firmware(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test turning on a client with a tunnel id does not stop other clients."""
    entity_id = _entity_id(hass, "MockVPN/MockSplitTunnel/wireguard_client")

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wireguard_client_start.assert_awaited_once_with(7707, 2002)
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
    entity_id = _entity_id(hass, "MockVPN/MockTunnel/wireguard_client")

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.wireguard_client_stop.assert_awaited_once_with(2001)


async def test_switch_unavailable_on_connect_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test switches become unavailable when the router is unreachable."""
    entity_id = _entity_id(hass, "iface_default_radio0")

    for name in POLLED_METHODS:
        getattr(mock_api, name).side_effect = TimeoutError
    # Two ticks: one for the router to latch the error, one for the entity
    # poll to pick it up (both run on the same clock)
    for _ in range(2):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_wifi_switch_oserror_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test WiFi switches handle OSError when turning on or off."""
    entity_id = _entity_id(hass, "iface_default_radio0")

    mock_api.wifi_iface_set_enabled.side_effect = OSError("Connection error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to disable WiFi interface default_radio0" in caplog.text

    caplog.clear()
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable WiFi interface default_radio0" in caplog.text


async def test_tailscale_switch_oserror_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test Tailscale switch handles OSError when turning on or off."""
    entity_id = _entity_id(hass, "tailscale")

    mock_api.tailscale_stop.side_effect = OSError("Socket error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to stop tailscale connection" in caplog.text

    caplog.clear()
    mock_api.tailscale_start.side_effect = OSError("Socket error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable tailscale connection" in caplog.text


async def test_tailscale_switch_lan_access(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test Tailscale switch lan_access property evaluates router config."""
    router = init_integration.runtime_data
    switch = TailscaleSwitch(router)

    router._tailscale_config = {
        "enabled": True,
        "lan_enabled": True,
        "lan_ip": "100.64.0.1",
        "wan_enabled": False,
    }
    assert switch.lan_access is True
    assert switch.extra_state_attributes == {"lan_access": True}

    router._tailscale_config = {
        "enabled": True,
        "lan_enabled": False,
        "lan_ip": "100.64.0.1",
        "wan_enabled": False,
    }
    assert switch.lan_access is False
    assert switch.extra_state_attributes == {"lan_access": False}

    router._tailscale_config = None
    assert switch.lan_access is None
    assert switch.extra_state_attributes == {}

    router._tailscale_config = cast(
        "TailscaleConfigResponse",
        {"enabled": True, "lan_ip": "100.64.0.1", "wan_enabled": False},
    )
    assert switch.lan_access is None
    assert switch.extra_state_attributes == {}


async def test_wireguard_switch_oserror_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test WireGuard switches handle OSError when turning on or off."""
    entity_id = _entity_id(hass, "MockVPN/MockTunnel/wireguard_client")

    mock_api.wireguard_client_stop.side_effect = OSError("Network unreachable")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to stop WG client" in caplog.text

    caplog.clear()
    mock_api.wireguard_client_start.side_effect = OSError("Network unreachable")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable WG client" in caplog.text


async def test_wifi_switch_api_client_error_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test WiFi switches handle APIClientError when turning on or off."""
    entity_id = _entity_id(hass, "iface_default_radio0")

    mock_api.wifi_iface_set_enabled.side_effect = NonZeroResponse("API error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to disable WiFi interface default_radio0" in caplog.text

    caplog.clear()
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable WiFi interface default_radio0" in caplog.text


async def test_tailscale_switch_api_client_error_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test Tailscale switch handles APIClientError when turning on or off."""
    entity_id = _entity_id(hass, "tailscale")

    mock_api.tailscale_stop.side_effect = NonZeroResponse("API error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to stop tailscale connection" in caplog.text

    caplog.clear()
    mock_api.tailscale_start.side_effect = NonZeroResponse("API error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable tailscale connection" in caplog.text


async def test_wireguard_switch_api_client_error_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test WireGuard switches handle APIClientError when turning on or off."""
    entity_id = _entity_id(hass, "MockVPN/MockTunnel/wireguard_client")

    mock_api.wireguard_client_stop.side_effect = NonZeroResponse("API error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to stop WG client" in caplog.text

    caplog.clear()
    mock_api.wireguard_client_start.side_effect = NonZeroResponse("API error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable WG client" in caplog.text
