"""Tests for the GL-iNet device trackers."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import (
    CONF_TRACK_RANDOMIZED_MAC,
    DOMAIN,
    TRACK_RANDOMIZED_MAC_DISABLED,
    TRACK_RANDOMIZED_MAC_ENABLED,
)
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
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done(wait_background_tasks=True)


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
        hass, mock_config_entry, ["B8:27:EB:44:55:66", "E8:DB:84:77:88:99"]
    )

    state = hass.states.get(_entity_id(hass, "E8:DB:84:77:88:99"))
    assert state is not None
    assert state.state == STATE_HOME
    assert state.attributes["interface_type"] == "2.4GHz"
    assert "last_time_reachable" in state.attributes

    state_cable = hass.states.get(_entity_id(hass, "B8:27:EB:44:55:66"))
    assert state_cable is not None
    assert state_cable.state == STATE_HOME
    assert state_cable.attributes["interface_type"] == "LAN"


async def test_tracker_goes_not_home_after_consider_home(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a vanished device stays home for the consider_home window only."""
    await _setup_with_known_devices(
        hass, mock_config_entry, ["E8:DB:84:77:88:99", "B8:27:EB:44:55:66"]
    )
    entity_id = _entity_id(hass, "E8:DB:84:77:88:99")

    # The device disappears, but the client list must stay non-empty
    remaining = {"B8:27:EB:44:55:66": deepcopy(MOCK_CLIENTS["B8:27:EB:44:55:66"])}
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
        ["B8:27:EB:44:55:66", "00:1E:67:A1:B2:C3", "00:bb:cc:dd:ee:03"],
    )
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("device_tracker", DOMAIN, "00:bb:cc:dd:ee:03")
        is None
    )

    clients = deepcopy(MOCK_CLIENTS)
    clients["00:bb:cc:dd:ee:03"] = {
        "alias": "Tablet",
        "name": "tablet",
        "ip": "192.168.1.102",
        "online": True,
        "type": 0,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    await _tick(hass, freezer)
    state = hass.states.get(_entity_id(hass, "00:bb:cc:dd:ee:03"))
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
        "00:bb:cc:dd:ee:99",
        config_entry=mock_config_entry,
        original_name="Old device",
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "00:bb:cc:dd:ee:99"))
    assert state is not None
    assert state.state == STATE_NOT_HOME


@pytest.mark.parametrize(
    "empty_name",
    [
        pytest.param("", id="empty_string"),
        pytest.param("*", id="asterisk"),
        pytest.param("   ", id="whitespace"),
    ],
)
async def test_device_with_no_name_tracked(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
    empty_name: str,
) -> None:
    """Test a client with neither alias nor valid name gets a tracker entity with MAC-derived name."""
    mac = "00:bb:cc:dd:ee:04"
    clients = deepcopy(MOCK_CLIENTS)
    clients[mac] = {
        "alias": "",
        "name": empty_name,
        "ip": "192.168.8.103",
        "online": True,
        "type": 0,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    await _setup_with_known_devices(
        hass,
        mock_config_entry,
        ["00:bb:cc:dd:ee:01", "00:bb:cc:dd:ee:02", mac],
    )

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, mac)
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_HOME
    assert state.name == mac.replace(":", "_")
    assert state.attributes["mac_randomized"] is False


async def test_randomized_mac_ignored_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a client using a randomized MAC is ignored by default."""
    random_mac = "9a:bb:cc:dd:ee:99"
    clients = deepcopy(MOCK_CLIENTS)
    clients[random_mac] = {
        "alias": "Phone",
        "name": "pixel",
        "ip": "192.168.8.199",
        "online": True,
        "type": 1,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, random_mac) is None


async def test_randomized_mac_disabled_option(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a randomized-MAC client is registered as disabled when option is disabled."""
    random_mac = "9a:bb:cc:dd:ee:99"
    clients = deepcopy(MOCK_CLIENTS)
    clients[random_mac] = {
        "alias": "Phone",
        "name": "pixel",
        "ip": "192.168.8.199",
        "online": True,
        "type": 1,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_TRACK_RANDOMIZED_MAC: TRACK_RANDOMIZED_MAC_DISABLED},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, random_mac)
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION


async def test_randomized_mac_enabled_option(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a randomized-MAC client is enabled when track_randomized_mac is enabled."""
    random_mac = "9a:bb:cc:dd:ee:99"
    clients = deepcopy(MOCK_CLIENTS)
    clients[random_mac] = {
        "alias": "Phone",
        "name": "pixel",
        "ip": "192.168.8.199",
        "online": True,
        "type": 1,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_TRACK_RANDOMIZED_MAC: TRACK_RANDOMIZED_MAC_ENABLED},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, random_mac))
    assert state is not None
    assert state.state == STATE_HOME
    assert state.attributes["mac_randomized"] is True


async def test_device_tracker_live_attributes_update(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test tracker entity reflects updated IP and name on subsequent polls."""
    mac = "B8:27:EB:44:55:66"
    await _setup_with_known_devices(hass, mock_config_entry, [mac])

    state = hass.states.get(_entity_id(hass, mac))
    assert state is not None
    assert state.attributes.get("ip") == "192.168.1.10"

    # Simulate router poll returning an updated IP and alias
    updated_clients = deepcopy(MOCK_CLIENTS)
    updated_clients[mac]["ip"] = "192.168.1.200"
    updated_clients[mac]["alias"] = "New HA Name"
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(
        updated_clients
    )

    await _tick(hass, freezer)

    state = hass.states.get(_entity_id(hass, mac))
    assert state is not None
    assert state.attributes.get("ip") == "192.168.1.200"
    assert "New HA Name" in state.name


async def test_restored_device_tracker_name_preserved_on_unassigned_update(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a restored device tracker preserves its friendly name when client poll reports no name."""
    mac = "00:bb:cc:dd:ee:88"
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "device_tracker",
        DOMAIN,
        mac,
        config_entry=mock_config_entry,
        original_name="GL-B1300",
    )

    clients = deepcopy(MOCK_CLIENTS)
    clients[mac] = {
        "alias": "",
        "name": "*",
        "ip": "192.168.8.105",
        "online": True,
        "type": 2,
    }
    mock_api.connected_clients.side_effect = lambda *_a, **_kw: deepcopy(clients)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, mac))
    assert state is not None
    assert state.name == "GL-B1300"
    assert state.attributes.get("friendly_name") == "GL-B1300"
