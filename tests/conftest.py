"""Shared fixtures for the GL-iNet integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

from gli4py import GLinet
from gli4py.mock import MockRouter
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from semver.version import Version

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .const import MOCK_MAC


class MockGLinet(GLinet):
    """GLinet client subclass allowing mutable logged_in for testing."""

    @property
    def logged_in(self) -> bool:
        """Return login state."""
        return self._logged_in

    @logged_in.setter
    def logged_in(self, value: bool) -> None:
        """Allow tests to modify login state."""
        self._logged_in = value


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations for every test."""
    return


@pytest.fixture
async def mock_router(socket_enabled: None) -> AsyncGenerator[MockRouter]:
    """Start an in-process MockRouter instance."""
    router = MockRouter(reboot_duration=0.0)
    await router.start()
    try:
        yield router
    finally:
        await router.stop()


@pytest.fixture
async def mock_api(hass: HomeAssistant, mock_router: MockRouter) -> MockGLinet:
    """Return a GLinet client wrapped with AsyncMock spies against MockRouter."""
    session = async_get_clientsession(hass)
    api = MockGLinet(
        session=session,
        base_url=f"http://127.0.0.1:{mock_router.actual_port}/rpc",
        sync=False,
    )
    api.sid = "mock-session-id"
    api._logged_in = True
    api._firmware_version = Version.parse("4.3.25")

    spied_methods = (
        "login",
        "router_reachable",
        "router_info",
        "router_get_status",
        "connected_clients",
        "wifi_ifaces_get",
        "wireguard_client_list",
        "wireguard_client_state",
        "tailscale_configured",
        "_tailscale_get_config",
        "tailscale_connection_state",
        "wireguard_client_start",
        "wireguard_client_stop",
        "tailscale_start",
        "tailscale_stop",
        "wifi_iface_set_enabled",
        "router_reboot",
    )
    for name in spied_methods:
        orig = getattr(api, name)
        spy = AsyncMock(wraps=orig)
        spy.__name__ = name
        setattr(api, name, spy)

    return api


@pytest.fixture
def mock_glinet(mock_api: MockGLinet) -> Generator[MagicMock]:
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
def mock_config_entry(mock_router: MockRouter) -> MockConfigEntry:
    """Return a mock config entry for the GL-iNet integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet B1300",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: f"http://127.0.0.1:{mock_router.actual_port}",
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
