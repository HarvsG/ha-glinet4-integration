"""Tests for the GLinetRouter update logic."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import AuthenticationError, TokenError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.router import (
    DEVICE_INTERFACE_TYPE_MAP,
    ClientDevInfo,
    DeviceInterfaceType,
    GLinetRouter,
)
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant

from .const import MOCK_STATUS, POLLED_METHODS


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 31
) -> None:
    """Advance frozen time and fire the polling interval."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_poll_updates_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test the periodic poll refreshes the router state."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.system_status["cpu"]["temperature"] == 42.5

    new_status = deepcopy(MOCK_STATUS)
    new_status["system"]["cpu"]["temperature"] = 50.0
    mock_api.router_get_status.side_effect = lambda *_a, **_kw: deepcopy(new_status)

    await _tick(hass, freezer)
    assert router.system_status["cpu"]["temperature"] == 50.0
    assert router.available


async def test_token_error_triggers_renew(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test a token error causes a re-login before the next API call."""
    router: GLinetRouter = init_integration.runtime_data
    login_count = mock_api.login.await_count

    original = mock_api.router_get_status.side_effect
    mock_api.router_get_status.side_effect = TokenError("expired")
    await _tick(hass, freezer)

    # The token was renewed within the same poll and later calls succeeded
    assert mock_api.login.await_count > login_count
    assert router.available

    mock_api.router_get_status.side_effect = original
    await _tick(hass, freezer)
    assert router.system_status["cpu"]["temperature"] == 42.5


async def test_timeout_latches_unavailable_and_recovers(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test the router latches unavailable on timeouts and recovers."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.available

    originals = {name: getattr(mock_api, name).side_effect for name in POLLED_METHODS}
    for name in POLLED_METHODS:
        getattr(mock_api, name).side_effect = TimeoutError
    await _tick(hass, freezer)
    assert not router.available

    for name, original in originals.items():
        getattr(mock_api, name).side_effect = original
    await _tick(hass, freezer)
    assert router.available


async def test_auth_failed_during_poll_starts_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test a failed token renewal during polling starts a reauth flow."""
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = AuthenticationError("password changed")

    await _tick(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_wireguard_malformed_config_skipped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test malformed WireGuard client configs are skipped without errors."""
    mock_api.wireguard_client_list.side_effect = lambda *_a, **_kw: [{"name": "broken"}]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    router: GLinetRouter = mock_config_entry.runtime_data
    assert router.wireguard_clients == {}


@pytest.mark.parametrize(
    ("type_index", "expected"),
    [
        (0, DeviceInterfaceType.WIFI_24),
        (1, DeviceInterfaceType.WIFI_5),
        (2, DeviceInterfaceType.LAN),
        (3, DeviceInterfaceType.WIFI_24_GUEST),
        (4, DeviceInterfaceType.WIFI_5_GUEST),
        (5, DeviceInterfaceType.UNKNOWN),
        (6, DeviceInterfaceType.DONGLE),
        (7, DeviceInterfaceType.BYPASS_ROUTE),
        (8, DeviceInterfaceType.UNKNOWN),
        (9, DeviceInterfaceType.MLO),
        (10, DeviceInterfaceType.MLO_GUEST),
        (11, DeviceInterfaceType.WIFI_6),
        (12, DeviceInterfaceType.WIFI_6_GUEST),
        (99, DeviceInterfaceType.UNKNOWN),
    ],
)
def test_device_interface_type_mapping(
    type_index: int, expected: DeviceInterfaceType
) -> None:
    """Test the API interface type index maps to the right interface type."""
    device = ClientDevInfo("aa:bb:cc:dd:ee:ff")
    device.update({"name": "dev", "ip": "192.168.8.2", "type": type_index})
    assert device.interface_type is expected


def test_device_interface_type_map_is_complete() -> None:
    """Test every enum member except aliases is reachable from the map."""
    assert set(DEVICE_INTERFACE_TYPE_MAP.values()) == set(DeviceInterfaceType)


def test_client_dev_info_consider_home(freezer: FrozenDateTimeFactory) -> None:
    """Test a disappeared device stays home for the consider_home window."""
    device = ClientDevInfo("aa:bb:cc:dd:ee:ff")
    device.update({"name": "dev", "ip": "192.168.8.2", "online": True, "type": 1})
    assert device.is_connected
    assert device.ip_address == "192.168.8.2"

    # Device vanishes from the router's client list
    freezer.tick(timedelta(seconds=170))
    device.update(None, consider_home=180)
    assert device.is_connected
    assert device.ip_address is None

    freezer.tick(timedelta(seconds=30))
    device.update(None, consider_home=180)
    assert not device.is_connected
