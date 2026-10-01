"""Tests for the GL-iNet DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from gli4py.error_handling import APIClientError, NonZeroResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.coordinator import (
    MAX_CONSECUTIVE_AUTH_FAILURES,
    GLinetData,
    GLinetDataUpdateCoordinator,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_coordinator_update_success(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test coordinator successful data update."""
    coordinator: GLinetDataUpdateCoordinator = init_integration.runtime_data
    assert isinstance(coordinator, GLinetDataUpdateCoordinator)

    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert isinstance(coordinator.data, GLinetData)
    assert coordinator.data.system_status is not None
    assert coordinator.data.client_counts is not None


async def test_coordinator_auth_failure_debounce(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test auth failure debouncing up to MAX_CONSECUTIVE_AUTH_FAILURES."""
    coordinator: GLinetDataUpdateCoordinator = init_integration.runtime_data
    router = coordinator.router

    with patch.object(
        router, "async_fetch_all", side_effect=ConfigEntryAuthFailed("auth error")
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
    coordinator: GLinetDataUpdateCoordinator = init_integration.runtime_data
    router = coordinator.router

    with (
        patch.object(router, "async_fetch_all", side_effect=exc),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


async def test_coordinator_recovery_resets_auth_counter(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test recovering after a transient auth failure resets failure counter and dismisses reauth."""
    coordinator: GLinetDataUpdateCoordinator = init_integration.runtime_data
    router = coordinator.router

    # Simulate 1 transient auth failure
    with (
        patch.object(
            router, "async_fetch_all", side_effect=ConfigEntryAuthFailed("auth error")
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
