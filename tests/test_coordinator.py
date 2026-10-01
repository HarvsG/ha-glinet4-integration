"""Tests for the GL-iNet DataUpdateCoordinators."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
from gli4py.error_handling import APIClientError, NonZeroResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import SCAN_INTERVAL, SWITCH_SCAN_INTERVAL
from custom_components.glinet.coordinator import (
    MAX_CONSECUTIVE_AUTH_FAILURES,
    GLinetRuntimeData,
    GLinetStatusCoordinator,
    GLinetStatusData,
    GLinetSwitchCoordinator,
    GLinetSwitchData,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_status_coordinator_update_success(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test status coordinator successful data update."""
    coordinator: GLinetStatusCoordinator = init_integration.runtime_data.coordinator
    assert isinstance(coordinator, GLinetStatusCoordinator)
    assert coordinator.update_interval == SCAN_INTERVAL

    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert isinstance(coordinator.data, GLinetStatusData)
    assert coordinator.data.system_status is not None
    assert coordinator.data.client_counts is not None
    assert coordinator.data.wan_status is not None


async def test_switch_coordinator_update_success(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test switch coordinator successful data update."""
    switch_coordinator: GLinetSwitchCoordinator = (
        init_integration.runtime_data.switch_coordinator
    )
    assert isinstance(switch_coordinator, GLinetSwitchCoordinator)
    assert switch_coordinator.update_interval == SWITCH_SCAN_INTERVAL

    await switch_coordinator.async_refresh()
    assert switch_coordinator.last_update_success is True
    assert isinstance(switch_coordinator.data, GLinetSwitchData)
    assert switch_coordinator.data.wifi_ifaces is not None


async def test_runtime_data_delegation_and_refresh(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test runtime data proxying and combined refresh."""
    runtime_data: GLinetRuntimeData = init_integration.runtime_data
    assert isinstance(runtime_data, GLinetRuntimeData)
    assert runtime_data.router is not None
    assert runtime_data.status_coordinator is runtime_data.coordinator

    # Test attribute proxying to router
    assert runtime_data.host == runtime_data.router.host

    # Test combined refresh
    await runtime_data.async_refresh()
    assert runtime_data.coordinator.last_update_success is True
    assert runtime_data.switch_coordinator.last_update_success is True


async def test_coordinator_auth_failure_debounce(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test auth failure debouncing up to MAX_CONSECUTIVE_AUTH_FAILURES."""
    coordinator: GLinetStatusCoordinator = init_integration.runtime_data.coordinator

    with patch.object(
        coordinator,
        "_async_fetch_data",
        side_effect=ConfigEntryAuthFailed("auth error"),
    ):
        # Attempt 1 -> UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator._consecutive_auth_errors == 1

        # Attempt 2 -> UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator._consecutive_auth_errors == 2

        # Attempt 3 -> ConfigEntryAuthFailed
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()
        assert coordinator._consecutive_auth_errors == MAX_CONSECUTIVE_AUTH_FAILURES


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("Connection timed out"),
        aiohttp.ClientError("Client connection dropped"),
        OSError("Network unreachable"),
        NonZeroResponse("API error response", 500),
        APIClientError("Generic API error"),
    ],
)
async def test_coordinator_communication_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, exc: Exception
) -> None:
    """Test communication errors raise UpdateFailed."""
    coordinator: GLinetStatusCoordinator = init_integration.runtime_data.coordinator

    with (
        patch.object(coordinator, "_async_fetch_data", side_effect=exc),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


async def test_coordinator_recovery_resets_auth_counter(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test recovering after a transient auth failure resets failure counter and dismisses reauth."""
    coordinator: GLinetStatusCoordinator = init_integration.runtime_data.coordinator
    router = coordinator.router

    # Simulate 1 transient auth failure
    with (
        patch.object(
            coordinator,
            "_async_fetch_data",
            side_effect=ConfigEntryAuthFailed("auth error"),
        ),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    assert coordinator._consecutive_auth_errors == 1

    # Simulate recovery
    with patch.object(router, "async_dismiss_reauth_flow") as mock_dismiss:
        await coordinator._async_update_data()
        assert coordinator._consecutive_auth_errors == 0
        mock_dismiss.assert_called_once()


async def test_switch_coordinator_unconfigured_endpoints_not_polled(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test unconfigured endpoints (Tailscale unconfigured, WireGuard no clients, LED unsupported) are not polled after startup."""
    switch_coordinator: GLinetSwitchCoordinator = (
        init_integration.runtime_data.switch_coordinator
    )
    router = switch_coordinator.router

    # Simulate unconfigured endpoints on the router
    router._wireguard_clients = {}
    router._tailscale_config = None
    router._led_supported = False
    switch_coordinator._initial_fetch = False

    with (
        patch.object(
            router, "update_wifi_ifaces_state", new_callable=AsyncMock
        ) as mock_wifi,
        patch.object(
            router, "update_wireguard_client_state", new_callable=AsyncMock
        ) as mock_wg,
        patch.object(
            router, "update_tailscale_connection_state", new_callable=AsyncMock
        ) as mock_ts,
        patch.object(router, "update_led_state", new_callable=AsyncMock) as mock_led,
    ):
        await switch_coordinator._async_update_data()
        mock_wifi.assert_awaited_once()
        mock_wg.assert_not_awaited()
        mock_ts.assert_not_awaited()
        mock_led.assert_not_awaited()
