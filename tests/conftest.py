"""Shared fixtures for the GL-iNet integration tests."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from gli4py.enums import TailscaleConnection
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import format_mac

from .const import (
    MOCK_CLIENTS,
    MOCK_HOST,
    MOCK_MAC,
    MOCK_ROUTER_INFO,
    MOCK_STATUS,
    MOCK_TAILSCALE_CONFIG,
    MOCK_WG_CLIENTS,
    MOCK_WG_STATE,
    MOCK_WIFI_IFACES,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations for every test."""
    return


def _api_method(name: str, return_value: Any = None) -> AsyncMock:
    """Build an AsyncMock API method with a __name__.

    GLinetRouter._update_platform logs api_callable.__name__; a bare
    AsyncMock attribute has no __name__ and the resulting AttributeError
    would be swallowed, silently marking the router unavailable.
    """
    method = AsyncMock(return_value=return_value)
    method.__name__ = name
    return method


def _canned(name: str, data: Any) -> AsyncMock:
    """Build an AsyncMock API method returning a deep copy of canned data."""
    method = AsyncMock(side_effect=lambda *_args, **_kwargs: deepcopy(data))
    method.__name__ = name
    return method


@pytest.fixture
def mock_api() -> MagicMock:
    """Return a mocked gli4py GLinet API client.

    Tests overriding a response should set the method's side_effect or
    return_value rather than replacing the AsyncMock, so __name__ survives.
    """
    api = MagicMock()
    api.login = _api_method("login")
    api.router_reachable = _api_method("router_reachable", True)
    api.router_info = _canned("router_info", MOCK_ROUTER_INFO)
    api.router_get_status = _canned("router_get_status", MOCK_STATUS)
    api.connected_clients = _canned("connected_clients", MOCK_CLIENTS)
    api.wifi_ifaces_get = _canned("wifi_ifaces_get", MOCK_WIFI_IFACES)
    api.wireguard_client_list = _canned("wireguard_client_list", MOCK_WG_CLIENTS)
    api.wireguard_client_state = _canned("wireguard_client_state", MOCK_WG_STATE)
    api.tailscale_configured = _api_method("tailscale_configured", True)
    api._tailscale_get_config = _canned("_tailscale_get_config", MOCK_TAILSCALE_CONFIG)
    api.tailscale_connection_state = _api_method(
        "tailscale_connection_state", TailscaleConnection.CONNECTED
    )
    api.wireguard_client_start = _api_method("wireguard_client_start")
    api.wireguard_client_stop = _api_method("wireguard_client_stop")
    api.tailscale_start = _api_method("tailscale_start")
    api.tailscale_stop = _api_method("tailscale_stop")
    api.wifi_iface_set_enabled = _api_method("wifi_iface_set_enabled")
    api.router_reboot = _api_method("router_reboot")
    api.logged_in = True
    api.sid = "mock-session-id"
    return api


@pytest.fixture
def mock_glinet(mock_api: MagicMock) -> Generator[MagicMock]:
    """Patch the GLinet class in both modules that construct it."""
    with (
        patch(
            "custom_components.glinet.router.GLinet", return_value=mock_api
        ) as router_cls,
        patch("custom_components.glinet.config_flow.GLinet", return_value=mock_api),
    ):
        yield router_cls


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent actual setup of the integration in pure config flow tests."""
    with patch(
        "custom_components.glinet.async_setup_entry", return_value=True
    ) as setup_mock:
        yield setup_mock


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry for the GL-iNet integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT6000",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: MOCK_HOST,
            CONF_PASSWORD: "goodlife",
        },
        options={CONF_CONSIDER_HOME: 180},
        unique_id=format_mac(MOCK_MAC),
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> MockConfigEntry:
    """Set up the GL-iNet integration for testing."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
