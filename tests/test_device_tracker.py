"""Tests for the GL-iNet device trackers."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import MOCK_CLIENTS


def _entity_id(hass: HomeAssistant, mac: str) -> str:
    """Resolve a device tracker entity id from the device MAC."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, mac)
    assert entity_id is not None
    return entity_id


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 31
) -> None:
    """Advance frozen time and fire the polling interval."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _setup_with_known_devices(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, macs: list[str]
) -> None:
    """Set up the integration with the given MACs known to the device registry.

    New ScannerEntities are disabled by default unless their MAC already
    exists in the device registry, so tests pre-register the tracked devices.
    """
    mock_config_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    for mac in macs:
        device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
        )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_tracker_entity_created_home(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test a connected client becomes a tracker entity that is home."""
    await _setup_with_known_devices(
        hass, mock_config_entry, ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    )

    state = hass.states.get(_entity_id(hass, "aa:bb:cc:dd:ee:01"))
    assert state is not None
    assert state.state == STATE_HOME
    assert state.attributes["interface_type"] == "5GHz"
    assert "last_time_reachable" in state.attributes


async def test_tracker_goes_not_home_after_consider_home(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a vanished device stays home for the consider_home window only."""
    await _setup_with_known_devices(
        hass, mock_config_entry, ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    )
    entity_id = _entity_id(hass, "aa:bb:cc:dd:ee:01")

    # The device disappears, but the client list must stay non-empty
    remaining = {"aa:bb:cc:dd:ee:02": deepcopy(MOCK_CLIENTS["aa:bb:cc:dd:ee:02"])}
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(remaining)

    # 31s elapsed: within the 180s consider_home window
    await _tick(hass, freezer)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_HOME

    # 231s elapsed: beyond the consider_home window
    await _tick(hass, freezer, seconds=200)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_NOT_HOME


async def test_new_device_mid_poll_creates_entity(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a device joining after setup gets a tracker entity."""
    await _setup_with_known_devices(
        hass,
        mock_config_entry,
        ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:03"],
    )
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("device_tracker", DOMAIN, "aa:bb:cc:dd:ee:03")
        is None
    )

    clients = deepcopy(MOCK_CLIENTS)
    clients["aa:bb:cc:dd:ee:03"] = {
        "alias": "Tablet",
        "name": "tablet",
        "ip": "192.168.8.102",
        "online": True,
        "type": 0,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    await _tick(hass, freezer)
    state = hass.states.get(_entity_id(hass, "aa:bb:cc:dd:ee:03"))
    assert state is not None
    assert state.state == STATE_HOME
    assert state.attributes["interface_type"] == "2.4GHz"


async def test_restored_registry_entities_recreated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test tracker entities from the registry are restored as not home."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "device_tracker",
        DOMAIN,
        "aa:bb:cc:dd:ee:99",
        config_entry=mock_config_entry,
        original_name="Old device",
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "aa:bb:cc:dd:ee:99"))
    assert state is not None
    assert state.state == STATE_NOT_HOME


async def test_device_with_no_name_skipped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a client with neither alias nor name gets no tracker entity."""
    clients = deepcopy(MOCK_CLIENTS)
    clients["aa:bb:cc:dd:ee:04"] = {
        "alias": "",
        "name": "",
        "ip": "192.168.8.103",
        "online": True,
        "type": 0,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("device_tracker", DOMAIN, "aa:bb:cc:dd:ee:04")
        is None
    )
