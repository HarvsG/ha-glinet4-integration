"""Tests for the GLinetRouter update logic."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import ssl
from unittest.mock import MagicMock, patch

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import (
    AuthenticationError,
    LockoutError,
    NonZeroResponse,
    TokenError,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.router import (
    DEVICE_INTERFACE_TYPE_MAP,
    ClientDevInfo,
    DeviceInterfaceType,
    GLinetRouter,
)
from homeassistant.components.device_tracker import DOMAIN as TRACKER_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import entity_registry as er

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


async def test_token_error_immediate_retry_recovers_state_same_tick(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test a token error immediately renews and retries in the same poll cycle without dropping data."""
    router: GLinetRouter = init_integration.runtime_data
    login_count = mock_api.login.await_count

    new_status = deepcopy(MOCK_STATUS)
    new_status["system"]["cpu"]["temperature"] = 55.0

    mock_api.router_get_status.side_effect = [
        TokenError("expired"),
        deepcopy(new_status),
    ]
    await _tick(hass, freezer)

    assert mock_api.login.await_count == login_count + 1
    assert router.system_status["cpu"]["temperature"] == 55.0
    assert router.available


async def test_token_error_retry_failure_does_not_loop(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test that persistent token error does not trigger an infinite retry loop."""
    login_count = mock_api.login.await_count
    status_count = mock_api.router_get_status.call_count

    mock_api.router_get_status.side_effect = TokenError("always expired")
    await _tick(hass, freezer)

    # Initial call + exactly 1 retry = 2 calls
    assert mock_api.router_get_status.call_count == status_count + 2
    assert mock_api.login.await_count == login_count + 1


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
    """Test a failed token renewal during polling starts a reauth flow after consecutive failures."""
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = AuthenticationError("password changed")

    # 1st and 2nd ticks: debounced, no reauth flow started yet
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    # 3rd consecutive failure triggers reauth flow
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_api_authentication_error_during_poll_triggers_renew_and_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test AuthenticationError code -32000 from an API call attempts token renewal and triggers reauth."""
    mock_api.router_get_status.side_effect = AuthenticationError(
        "Request returned error code -32000 (Access denied)"
    )
    mock_api.login.side_effect = AuthenticationError("Wrong password")

    # 1st and 2nd ticks: debounced
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    # 3rd tick: triggers reauth flow
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_api_lockout_error_during_renew_triggers_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test lockout error code -32003 during login is recognized as auth error and triggers reauth."""
    mock_api.router_get_status.side_effect = AuthenticationError(
        "Request returned error code -32000 (Access denied)"
    )
    mock_api.login.side_effect = LockoutError(
        "Request returned error code -32003 (Login fail number over limit)"
    )

    # 1st and 2nd ticks: debounced
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    # 3rd tick: triggers reauth flow
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_token_error_during_renew_does_not_start_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test a token error during renewal does not trigger reauth."""
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = TokenError("session invalid")

    await _tick(hass, freezer)
    await _tick(hass, freezer)
    await _tick(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_auth_error_debounced_transient_failure_does_not_prompt(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test transient auth errors do not start a reauth flow."""
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = AuthenticationError("temporary error")

    # 1st and 2nd failures
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    # Success on next tick resets the failure counter
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = deepcopy(MOCK_STATUS)
    mock_api.login.side_effect = None
    await _tick(hass, freezer)

    # Another single failure later still does not trigger reauth
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = AuthenticationError("temporary error")
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_reauth_flow_aborted_when_router_recovers(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test that an active reauth flow is dismissed once the router recovers."""
    mock_api.router_get_status.side_effect = TokenError("expired")
    mock_api.login.side_effect = AuthenticationError("password changed")

    # Trigger reauth after 3 consecutive failures
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    await _tick(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)

    # Router comes back online and successfully authenticates
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = deepcopy(MOCK_STATUS)
    mock_api.login.side_effect = None

    await _tick(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_connect_error_does_not_hammer_login(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test that connection timeouts during poll do not hammer the login endpoint."""
    for name in POLLED_METHODS:
        getattr(mock_api, name).side_effect = TimeoutError

    initial_login_count = mock_api.login.call_count
    await _tick(hass, freezer)

    # Login should not have been called during the connection error poll
    assert mock_api.login.call_count == initial_login_count


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


async def test_router_create_api_verify_ssl(hass: HomeAssistant) -> None:
    """Test router _create_api respects verify_ssl configuration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT6000",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: "https://192.168.8.1",
            CONF_PASSWORD: "goodlife",
        },
        options={CONF_VERIFY_SSL: False},
        unique_id="94:83:c4:aa:bb:cc",
    )
    with patch(
        "custom_components.glinet.router.async_get_clientsession"
    ) as mock_get_session:
        router = GLinetRouter(hass, entry)
        router._create_api()
        mock_get_session.assert_called_once_with(hass, verify_ssl=False)


async def test_router_renew_token_ssl_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test renew_token logs clear message when SSL certificate verification fails."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT1300",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: "https://192.168.0.1",
            CONF_PASSWORD: "goodlife",
        },
        options={CONF_VERIFY_SSL: True},
        unique_id="94:83:c4:14:73:76",
    )
    router = GLinetRouter(hass, entry)
    mock_api = MagicMock()
    ssl_err = ssl.SSLCertVerificationError(
        "certificate verify failed: self-signed certificate"
    )
    cert_err = aiohttp.ClientConnectorCertificateError(None, ssl_err)  # type: ignore[arg-type]
    wrapped_err = KeyError("Parameter Exception:")
    wrapped_err.__cause__ = cert_err
    mock_api.login.side_effect = wrapped_err
    router._api = mock_api

    with pytest.raises(KeyError):
        await router.renew_token()

    assert (
        "SSL certificate verification failed for GL-iNet router https://192.168.0.1"
        in caplog.text
    )
    assert "self-signed certificate" in caplog.text


async def test_router_async_init_ssl_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test async_init raises ConfigEntryNotReady without traceback dump on SSL error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT1300",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: "https://192.168.0.1",
            CONF_PASSWORD: "goodlife",
        },
        options={CONF_VERIFY_SSL: True},
        unique_id="94:83:c4:14:73:76",
    )
    router = GLinetRouter(hass, entry)
    ssl_err = ssl.SSLCertVerificationError(
        "certificate verify failed: self-signed certificate"
    )
    cert_err = aiohttp.ClientConnectorCertificateError(None, ssl_err)  # type: ignore[arg-type]
    wrapped_err = KeyError("Parameter Exception:")
    wrapped_err.__cause__ = cert_err

    with (
        patch.object(router, "_create_api"),
        patch.object(router, "renew_token", side_effect=wrapped_err),
        pytest.raises(ConfigEntryNotReady) as exc_info,
    ):
        await router.async_init()

    assert "SSL certificate verification failed for GL-iNet router" in str(
        exc_info.value
    )
    # The broad exception traceback should not have been logged
    assert "Error connecting to GL-iNet router" not in caplog.text


async def test_empty_client_list_ignored_during_reboot_grace(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test an empty client list right after reboot does not disconnect devices."""
    router: GLinetRouter = init_integration.runtime_data
    # Ensure devices are tracked
    assert len(router.devices) > 0
    test_device = next(iter(router.devices.values()))
    assert test_device.is_connected

    # Set router uptime to low value (within grace period)
    router._system_status["uptime"] = 30
    mock_api.connected_clients.side_effect = None
    mock_api.connected_clients.return_value = {}

    await router.update_device_trackers()
    assert test_device.is_connected
    assert router.connected_devices_count > 0


async def test_empty_client_list_processed_after_reboot_grace(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test an empty client list outside grace period updates device connection states."""
    router: GLinetRouter = init_integration.runtime_data
    assert len(router.devices) > 0
    test_device = next(iter(router.devices.values()))
    assert test_device.is_connected

    # Set router uptime beyond grace period
    router._system_status["uptime"] = 1000
    mock_api.connected_clients.side_effect = None
    mock_api.connected_clients.return_value = {}

    await router.update_device_trackers()
    assert router.connected_devices_count == 0

    # Advance past consider_home
    freezer.tick(timedelta(seconds=200))
    await router.update_device_trackers()
    assert not test_device.is_connected


def test_client_dev_info_preserves_name_on_unassigned_update() -> None:
    """Test that a device with an existing name does not lose it to asterisk or empty updates."""
    device = ClientDevInfo("aa:bb:cc:dd:ee:ff", "GL-B1300")
    assert device.name == "GL-B1300"

    # Asterisk name from DHCP/ARP must not overwrite existing name
    device.update({"name": "*", "ip": "192.168.8.2", "online": True})
    assert device.name == "GL-B1300"

    # Empty or whitespace name must not overwrite existing name
    device.update({"name": "", "ip": "192.168.8.2", "online": True})
    assert device.name == "GL-B1300"
    device.update({"name": "   ", "ip": "192.168.8.2", "online": True})
    assert device.name == "GL-B1300"

    # Valid name updates the device name
    device.update({"name": "GL-B1300-New", "ip": "192.168.8.2", "online": True})
    assert device.name == "GL-B1300-New"

    # Alias takes precedence
    device.update(
        {"alias": "Living Room AP", "name": "*", "ip": "192.168.8.2", "online": True}
    )
    assert device.name == "Living Room AP"


def test_client_dev_info_fallback_name_when_no_initial_name() -> None:
    """Test that a device initialized without a name falls back to underscored MAC on unassigned update."""
    mac = "aa:bb:cc:dd:ee:ff"
    device = ClientDevInfo(mac)
    assert device.name is None

    device.update({"name": "*", "ip": "192.168.8.2", "online": True})
    assert device.name == mac.replace(":", "_")


async def test_router_async_init_device_info_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test async_init raises ConfigEntryNotReady when router_info fails."""
    router = GLinetRouter(hass, mock_config_entry)
    mock_api.router_info.side_effect = aiohttp.ClientError("Failed to fetch info")

    with pytest.raises(ConfigEntryNotReady):
        await router.async_init()

    assert "Error getting basic device info from GL-iNet router" in caplog.text


async def test_router_create_api_missing_password_raises_config_entry_error(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test _create_api raises ConfigEntryError when password is missing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT6000",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.8.1",
        },
        unique_id="94:83:c4:aa:bb:cc",
    )
    router = GLinetRouter(hass, entry)
    with pytest.raises(ConfigEntryError):
        router._create_api()

    assert "no auth details found in configuration" in caplog.text


async def test_update_platform_non_zero_response(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test NonZeroResponse marks router unavailable and logs error."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.available

    mock_api.router_get_status.side_effect = NonZeroResponse("Error code 1")
    result = await router._update_platform(mock_api.router_get_status)
    assert result is None
    assert not router.available
    assert "responded, but with an error code" in caplog.text


async def test_update_platform_broad_exception(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test unexpected exception during polling marks router unavailable."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.available

    mock_api.router_get_status.side_effect = RuntimeError("Unexpected internal crash")
    result = await router._update_platform(mock_api.router_get_status)
    assert result is None
    assert not router.available
    assert "responded with an unexpected error" in caplog.text


async def test_malformed_wan_interface_warning_deduplicated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test malformed WAN interface warns once and deduplicates subsequent warnings."""
    router: GLinetRouter = init_integration.runtime_data
    status = {
        "system": {"uptime": 1000},
        "network": [{"interface": "bad_wan"}],
    }
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = status

    await router.update_system_status()
    assert "returned a malformed entry for WAN interface bad_wan" in caplog.text
    assert "bad_wan" in router._warned_wan_interfaces

    caplog.clear()
    await router.update_system_status()
    assert "returned a malformed entry for WAN interface bad_wan" not in caplog.text


async def test_update_device_trackers_empty_response_during_startup(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test empty payload from connected_clients exits cleanly without wiping known devices."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.devices
    mock_api.connected_clients.side_effect = None
    mock_api.connected_clients.return_value = {}

    await router.update_device_trackers()
    # Devices are retained (no wipe on empty response with non-zero uptime)
    assert router.devices


async def test_tailscale_unconfigured_and_connection_state_none(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test Tailscale state updates when unconfigured and when connection query fails."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.tailscale_configured is True
    assert router.tailscale_connection is True
    assert router.tailscale_config is not None

    # Query fails for connection state -> retains previous state
    mock_api.tailscale_connection_state.side_effect = None
    mock_api.tailscale_connection_state.return_value = None
    await router.update_tailscale_state()
    assert router.tailscale_connection is True

    # Tailscale becomes unconfigured
    mock_api.tailscale_configured.side_effect = None
    mock_api.tailscale_configured.return_value = False
    await router.update_tailscale_state()
    assert router.tailscale_configured is False
    assert router.tailscale_config is None
    assert router.tailscale_connection is None


async def test_wireguard_state_empty_response(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test empty wireguard_client_state response returns early without changes."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.wireguard_clients
    mock_api.wireguard_client_state.side_effect = None
    mock_api.wireguard_client_state.return_value = []

    await router.update_wireguard_client_state()
    # Clients are still present
    assert router.wireguard_clients


async def test_wireguard_state_skips_unknown_peer(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test wireguard state skips entries with unknown peer ids."""
    router: GLinetRouter = init_integration.runtime_data
    mock_api.wireguard_client_state.side_effect = None
    mock_api.wireguard_client_state.return_value = [
        {
            "peer_id": 9999,
            "status": 1,
            "enabled": True,
            "domain": "",
            "group_id": 0,
            "ipv4": "",
            "ipv6": "",
            "log": "",
            "name": "",
            "port": 0,
            "proxy": False,
            "rx_bytes": 0,
            "tx_bytes": 0,
        },
    ]

    await router.update_wireguard_client_state()
    # Unknown peer 9999 was not added to connected clients
    assert router.connected_wireguard_clients == []


async def test_router_properties(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test router properties return expected configuration values."""
    router: GLinetRouter = init_integration.runtime_data
    assert router.host == "http://192.168.8.1"
    assert router.unique_id == "94:83:c4:aa:bb:cc"
    assert router.api is not None
    assert router.sw_version == "4.8.2"

    device = ClientDevInfo("aa:bb:cc:dd:ee:ff")
    assert device.last_activity is not None


async def test_router_async_init_renew_token_auth_failed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test async_init raises ConfigEntryAuthFailed when renew_token fails auth."""
    router = GLinetRouter(hass, mock_config_entry)
    mock_api.login.side_effect = AuthenticationError("Wrong password")

    with pytest.raises(ConfigEntryAuthFailed):
        await router.async_init()


async def test_router_async_init_renew_token_generic_exception(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test async_init raises ConfigEntryNotReady when renew_token encounters generic error."""
    router = GLinetRouter(hass, mock_config_entry)
    mock_api.login.side_effect = aiohttp.ClientConnectionError("Network dropped")

    with pytest.raises(ConfigEntryNotReady):
        await router.async_init()

    assert "Error connecting to GL-iNet router" in caplog.text


async def test_renew_token_non_ssl_warning(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test renew_token logs warning for non-SSL connection error."""
    router: GLinetRouter = init_integration.runtime_data
    mock_api.login.side_effect = aiohttp.ClientConnectionError("Connection timeout")

    with pytest.raises(aiohttp.ClientConnectionError):
        await router.renew_token()

    assert "Could not connect to GL-iNet router to renew token" in caplog.text


async def test_setup_restores_persisted_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test router setup restores previously persisted tracker entries from registry."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        TRACKER_DOMAIN,
        DOMAIN,
        "aa:bb:cc:11:22:33",
        config_entry=mock_config_entry,
        original_name="Saved Device",
    )

    router = GLinetRouter(hass, mock_config_entry)
    await router.setup()
    assert "aa:bb:cc:11:22:33" in router.devices
    assert router.devices["aa:bb:cc:11:22:33"].name == "Saved Device"
    router.unload()


async def test_update_device_trackers_skips_unassigned_client(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test update_device_trackers skips unassigned new client with asterisk name."""
    router: GLinetRouter = init_integration.runtime_data
    mock_api.connected_clients.side_effect = None
    mock_api.connected_clients.return_value = {
        "aa:bb:cc:dd:ee:99": {"name": "*", "ip": "192.168.8.199"}
    }

    await router.update_device_trackers()
    assert "aa:bb:cc:dd:ee:99" not in router.devices


async def test_update_system_status_registers_new_wan_interface(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test update_system_status registers newly discovered up WAN interface."""
    router: GLinetRouter = init_integration.runtime_data
    status = {
        "system": {"uptime": 1000},
        "network": [{"interface": "new_wan_iface", "up": True, "online": True}],
    }
    mock_api.router_get_status.side_effect = None
    mock_api.router_get_status.return_value = status

    await router.update_system_status()
    assert "new_wan_iface" in router._known_wan_interfaces
