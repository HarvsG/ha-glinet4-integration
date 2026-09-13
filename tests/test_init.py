"""Tests for the GL-iNet integration setup and unload."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import AuthenticationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet import async_remove_config_entry_device
from custom_components.glinet.const import DOMAIN
from custom_components.glinet.router import GLinetRouter
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er


async def test_setup_entry_ok(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a successful setup creates entities on all platforms."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert isinstance(init_integration.runtime_data, GLinetRouter)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, init_integration.entry_id)
    platforms = {entry.domain for entry in entries}
    assert platforms == {"button", "device_tracker", "sensor", "switch"}


async def test_unload_entry(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test unloading cancels the polling timer."""
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED

    mock_api.router_get_status.reset_mock()
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock_api.router_get_status.await_count == 0


async def test_setup_entry_not_ready(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a connection error during setup puts the entry in retry state."""
    mock_api.login.side_effect = TimeoutError
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_auth_failed_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test an authentication error during setup starts a reauth flow."""
    mock_api.login.side_effect = AuthenticationError("bad password")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_update_listener_reloads_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test an options update reloads the config entry."""
    assert mock_glinet.call_count == 1

    hass.config_entries.async_update_entry(
        init_integration, options={CONF_CONSIDER_HOME: 60}
    )
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.LOADED
    assert mock_glinet.call_count == 2
    router: GLinetRouter = init_integration.runtime_data
    assert router._consider_home == pytest.approx(60)


async def test_remove_config_entry_device_router_rejected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that the router itself cannot be removed via device registry."""
    device_registry = dr.async_get(hass)
    router_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, init_integration.unique_id), init_integration.entry_id
    )
    assert router_device is not None
    assert not await async_remove_config_entry_device(
        hass, init_integration, router_device
    )


async def test_remove_config_entry_device_connected_client_rejected(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that an actively connected client device cannot be removed."""
    device_registry = dr.async_get(hass)
    active_mac = "aa:bb:cc:dd:ee:01"
    client_device = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, active_mac)},
    )
    assert not await async_remove_config_entry_device(
        hass, init_integration, client_device
    )
    router: GLinetRouter = init_integration.runtime_data
    assert active_mac in router.devices


async def test_remove_config_entry_device_disconnected_client_success(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that a disconnected client device can be removed and pruned."""
    device_registry = dr.async_get(hass)
    client_mac = "aa:bb:cc:dd:ee:01"
    router: GLinetRouter = init_integration.runtime_data
    router.devices[client_mac]._connected = False

    client_device = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, client_mac)},
    )
    assert await async_remove_config_entry_device(hass, init_integration, client_device)
    assert client_mac not in router.devices


async def test_remove_config_entry_device_unknown_device_success(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that an unknown/stale client device not in memory can be removed."""
    device_registry = dr.async_get(hass)
    stale_device = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:99")},
    )
    assert await async_remove_config_entry_device(hass, init_integration, stale_device)


async def test_remove_config_entry_device_invalid_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test that devices without MAC connections are rejected."""
    device_registry = dr.async_get(hass)
    no_mac_device = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={("other_domain", "random_id")},
    )
    assert not await async_remove_config_entry_device(
        hass, init_integration, no_mac_device
    )
