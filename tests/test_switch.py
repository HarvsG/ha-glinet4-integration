"""Tests for the GL-iNet switches."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock, call

from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import APIClientError, NonZeroResponse
from gli4py.models import (
    PortForwardListResponse,
    PortForwardRule,
    TailscaleConfigResponse,
    TailscaleConnection,
    WireguardClientListItem,
    WireguardStatusItem,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.switch import LedSwitch, TailscaleSwitch
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
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

from .const import MOCK_MAC, MOCK_PORT_FORWARD_RULES, POLLED_METHODS

WG_CLIENTS_OLD_FIRMWARE = [
    WireguardClientListItem(name="wg_home", peer_id=1, group_id=10),
    WireguardClientListItem(name="wg_office", peer_id=2, group_id=10),
]

WG_STATE_OLD_FIRMWARE = [
    WireguardStatusItem(peer_id=1, status=1),
    WireguardStatusItem(peer_id=2, status=0),
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


async def test_led_switch_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test the LED switch reflects state and toggles via the API."""
    entity_id = _entity_id(hass, "led")

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.led_set.assert_awaited_with(False)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_api.led_set.assert_awaited_with(True)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON


async def test_led_switch_not_created_when_unsupported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test no LED switch is created when the router does not support LEDs."""
    mock_api.led_get_config.side_effect = NonZeroResponse("API error")

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    unique_id = f"glinet_switch/{MOCK_MAC}/led"
    assert registry.async_get_entity_id("switch", DOMAIN, unique_id) is None


async def test_led_probe_network_error_retries_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """A network error probing LED support should retry setup, not disable it."""
    mock_api.led_get_config.side_effect = TimeoutError

    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_led_switch_oserror_handling(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the LED switch handles OSError when turning on or off."""
    entity_id = _entity_id(hass, "led")

    mock_api.led_set.side_effect = OSError("Connection error")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to disable router LEDs" in caplog.text

    caplog.clear()
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert "Unable to enable router LEDs" in caplog.text


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
    coordinator = init_integration.runtime_data.switch_coordinator
    router = coordinator.router
    switch = TailscaleSwitch(coordinator)

    router._tailscale_config = TailscaleConfigResponse.from_dict(
        {
            "enabled": True,
            "lan_enabled": True,
            "lan_ip": "100.64.0.1",
            "wan_enabled": False,
        }
    )
    assert switch.lan_access is True
    assert switch.extra_state_attributes == {"lan_access": True}

    router._tailscale_config = TailscaleConfigResponse.from_dict(
        {
            "enabled": True,
            "lan_enabled": False,
            "lan_ip": "100.64.0.1",
            "wan_enabled": False,
        }
    )
    assert switch.lan_access is False
    assert switch.extra_state_attributes == {"lan_access": False}

    router._tailscale_config = None
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


async def test_wifi_switch_is_on_and_name_fallbacks(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test WifiApSwitch is_on and name fallback paths."""
    entity_id = _entity_id(hass, "iface_default_radio0")
    switch = hass.data["entity_components"]["switch"].get_entity(entity_id)

    # is_on fallback: _attr_is_on = None -> reads coordinator data
    switch._attr_is_on = None
    assert switch.is_on is True

    # is_on None fallback: no matching iface in data -> returns None
    original_ifaces = switch.coordinator.data.wifi_ifaces
    switch.coordinator.data.wifi_ifaces = {}
    assert switch.is_on is None

    # name fallback: ssid empty -> falls to iface.name
    mock_iface = MagicMock(
        enabled=True, ssid="", guest=False, hidden=False, encryption="psk2"
    )
    mock_iface.name = "test_name"
    switch.coordinator.data.wifi_ifaces = {"default_radio0": mock_iface}
    assert switch.name == "test_name"

    # name fallback: ssid and name both empty -> falls to iface_name
    mock_iface.name = ""
    assert switch.name == "default_radio0"

    switch.coordinator.data.wifi_ifaces = original_ifaces


async def test_tailscale_switch_init_and_is_on_fallbacks(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test TailscaleSwitch init branch and is_on fallbacks."""
    coordinator = init_integration.runtime_data.switch_coordinator

    # is_on fallback: _attr_is_on = None with valid coordinator data
    entity_id = _entity_id(hass, "tailscale")
    switch = hass.data["entity_components"]["switch"].get_entity(entity_id)
    switch._attr_is_on = None
    result = switch.is_on
    assert isinstance(result, bool)

    # is_on None fallback: tailscale_connection is None -> returns None
    original_conn = switch.coordinator.data.tailscale_connection
    switch.coordinator.data.tailscale_connection = None
    assert switch.is_on is None
    switch.coordinator.data.tailscale_connection = original_conn

    # Init fallback: coordinator.data is None -> reads from router
    coordinator_data = coordinator.data
    coordinator.data = None
    new_switch = TailscaleSwitch(coordinator)
    # Exercises the else branch in __init__
    assert new_switch._attr_is_on == coordinator.router.tailscale_connection
    coordinator.data = coordinator_data


async def test_wireguard_switch_is_on_fallbacks(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test WireGuardSwitch is_on fallbacks."""
    entity_id = _entity_id(hass, "MockVPN/MockTunnel/wireguard_client")
    switch = hass.data["entity_components"]["switch"].get_entity(entity_id)

    # is_on fallback: _attr_is_on = None with coordinator data
    switch._attr_is_on = None
    result = switch.is_on
    assert isinstance(result, bool)

    # is_on fallback: wireguard_connections is None -> falls to router
    original_conns = switch.coordinator.data.wireguard_connections
    switch.coordinator.data.wireguard_connections = None
    result = switch.is_on
    assert isinstance(result, bool)
    switch.coordinator.data.wireguard_connections = original_conns


async def test_led_switch_init_and_is_on_fallbacks(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test LedSwitch init branch and is_on fallbacks."""
    coordinator = init_integration.runtime_data.switch_coordinator

    # is_on fallback: _attr_is_on = None with valid coordinator data
    entity_id = _entity_id(hass, "led")
    switch = hass.data["entity_components"]["switch"].get_entity(entity_id)
    switch._attr_is_on = None
    result = switch.is_on
    assert isinstance(result, bool)

    # is_on None fallback: led_enabled is None -> returns None
    original_led = switch.coordinator.data.led_enabled
    switch.coordinator.data.led_enabled = None
    assert switch.is_on is None
    switch.coordinator.data.led_enabled = original_led

    # Init fallback: coordinator.data is None -> reads from router
    coordinator_data = coordinator.data
    coordinator.data = None
    new_switch = LedSwitch(coordinator)
    # Exercises the else branch in __init__
    assert new_switch._attr_is_on == coordinator.router.led_enabled
    coordinator.data = coordinator_data


async def test_port_forward_switch_state_and_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test port forward switch setup, disabled-by-default status, and state attributes."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    entity_id2 = _entity_id(hass, "port_forward_cfg2b3837")

    entry1 = registry.async_get(entity_id1)
    entry2 = registry.async_get(entity_id2)
    assert entry1 is not None
    assert entry2 is not None
    assert entry1.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert entry2.disabled_by == er.RegistryEntryDisabler.INTEGRATION

    # Enable entities and reload to populate states
    registry.async_update_entity(entity_id1, disabled_by=None)
    registry.async_update_entity(entity_id2, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    state1 = hass.states.get(entity_id1)
    assert state1 is not None
    assert state1.state == STATE_ON
    assert state1.attributes["protocol"] == "tcp udp"
    assert state1.attributes["external_port"] == 1234
    assert state1.attributes["internal_ip"] == "192.168.0.160"
    assert state1.attributes["internal_port"] == 1234
    assert "rule_id" not in state1.attributes

    state2 = hass.states.get(entity_id2)
    assert state2 is not None
    assert state2.state == STATE_OFF
    assert state2.attributes["protocol"] == "tcp"
    assert state2.attributes["external_port"] == 5000
    assert state2.attributes["internal_ip"] == "192.168.0.161"
    assert state2.attributes["internal_port"] == 5000


async def test_port_forward_switch_turn_on_and_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test toggling a port forward switch calls set_port_forward with updated rule."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    registry.async_update_entity(entity_id1, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    # Turn off cfg2a3837 (currently ON)
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id1}, blocking=True
    )
    mock_api.set_port_forward.assert_awaited()
    called_rule = mock_api.set_port_forward.call_args[0][0]
    assert called_rule.id == "cfg2a3837"
    assert called_rule.enabled is False
    assert hass.states.get(entity_id1).state == STATE_OFF

    # Turn on cfg2a3837
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id1}, blocking=True
    )
    called_rule = mock_api.set_port_forward.call_args[0][0]
    assert called_rule.id == "cfg2a3837"
    assert called_rule.enabled is True
    assert hass.states.get(entity_id1).state == STATE_ON


async def test_port_forward_switch_turn_on_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test turn_on rolls back optimistic state when API call fails."""
    registry = er.async_get(hass)
    entity_id2 = _entity_id(hass, "port_forward_cfg2b3837")
    registry.async_update_entity(entity_id2, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    mock_api.set_port_forward.side_effect = APIClientError("API failed")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id2}, blocking=True
    )
    # State reverts back to OFF on error
    assert hass.states.get(entity_id2).state == STATE_OFF


async def test_port_forward_switch_coordinator_update(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test switch updates state when coordinator fetches updated rule from router."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    registry.async_update_entity(entity_id1, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    updated_rules = [
        PortForwardRule(
            id="cfg2a3837",
            name="test",
            enabled=False,
            src="wan",
            dest="lan",
            src_dport="1234",
            dest_ip="192.168.0.160",
            dest_port=1234,
            proto="tcp udp",
        )
    ]
    mock_api.get_port_forward_list.return_value = PortForwardListResponse(
        res=updated_rules
    )
    coordinator = init_integration.runtime_data.switch_coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id1).state == STATE_OFF


async def test_port_forward_switch_dynamic_addition(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test a new rule added to the router dynamically creates a new switch entity."""
    new_rule = PortForwardRule(
        id="cfg2c3837",
        name="test3",
        enabled=True,
        src="wan",
        dest="lan",
        src_dport="8080",
        dest_ip="192.168.0.162",
        dest_port=8080,
        proto="tcp",
    )
    current_rules = [*MOCK_PORT_FORWARD_RULES, new_rule]
    mock_api.get_port_forward_list.return_value = PortForwardListResponse(
        res=current_rules
    )

    coordinator = init_integration.runtime_data.switch_coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id3 = _entity_id(hass, "port_forward_cfg2c3837")
    registry = er.async_get(hass)
    entry3 = registry.async_get(entity_id3)
    assert entry3 is not None
    assert entry3.disabled_by == er.RegistryEntryDisabler.INTEGRATION


async def test_port_forward_switch_deleted_rule_becomes_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test switch becomes unavailable when rule is deleted, and orphaned on reload."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    registry.async_update_entity(entity_id1, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id1).state == STATE_ON

    # Rule cfg2a3837 deleted on router
    mock_api.get_port_forward_list.return_value = PortForwardListResponse(
        res=[MOCK_PORT_FORWARD_RULES[1]]
    )
    coordinator = init_integration.runtime_data.switch_coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # In HA runtime, missing rule becomes unavailable
    assert hass.states.get(entity_id1).state == STATE_UNAVAILABLE

    # On reload, rule is not loaded by the integration, so entity is not instantiated
    # and HA marks it as a restored state in the state machine
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.data["entity_components"]["switch"].get_entity(entity_id1) is None
    state_after_reload = hass.states.get(entity_id1)
    assert state_after_reload is not None
    assert state_after_reload.state == STATE_UNAVAILABLE
    assert state_after_reload.attributes.get("restored") is True
    assert registry.async_get(entity_id1) is not None


async def test_port_forward_switch_turn_off_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test turn_off rolls back optimistic state when API call fails."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    registry.async_update_entity(entity_id1, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    mock_api.set_port_forward.side_effect = APIClientError("API failed")
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id1}, blocking=True
    )
    # State reverts back to ON on error
    assert hass.states.get(entity_id1).state == STATE_ON


async def test_port_forward_switch_fallbacks(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    """Test PortForwardSwitch fallback branches for is_on, attributes, and actions."""
    registry = er.async_get(hass)
    entity_id1 = _entity_id(hass, "port_forward_cfg2a3837")
    registry.async_update_entity(entity_id1, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    switch = hass.data["entity_components"]["switch"].get_entity(entity_id1)
    assert switch is not None

    # is_on fallback: _attr_is_on = None -> reads from rule
    switch._attr_is_on = None
    assert switch.is_on is True

    # coordinator.data is None fallback -> reads from router
    original_data = switch.coordinator.data
    switch.coordinator.data = None
    assert switch.rule == switch.router.port_forward_rules["cfg2a3837"]
    switch.coordinator.data = original_data

    # When rule is None
    switch._rule_id = "nonexistent_rule"
    assert switch.rule is None
    switch._attr_is_on = None
    assert switch.is_on is None
    assert switch.extra_state_attributes == {}

    # Turn on / turn off when rule is None do nothing
    mock_api.set_port_forward.reset_mock()
    await switch.async_turn_on()
    await switch.async_turn_off()
    mock_api.set_port_forward.assert_not_called()

    # When dest_port is string
    rule_str = PortForwardRule(
        id="cfg2d3837",
        name="test_str",
        enabled=True,
        src="wan",
        dest="lan",
        src_dport="80",
        dest_ip="192.168.0.10",
        dest_port="80",
        proto="tcp",
    )
    switch.router._port_forward_rules["cfg2d3837"] = rule_str
    switch._rule_id = "cfg2d3837"
    switch.coordinator.data = None
    assert switch.extra_state_attributes["internal_port"] == 80
