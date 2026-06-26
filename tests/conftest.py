"""Common fixtures for the GL-iNet integration tests.

The suite is **profile-driven**: every directory under ``tests/fixtures`` that
contains a ``profile.json`` is a router "profile" (a model + firmware + captured
API responses). The ``profile`` fixture is parametrized over every such profile,
so each test that consumes it runs once per profile and its node id gains a
``[<profile-id>]`` suffix.

Only ``mt6000`` is a real, sanitised capture; the rest are derived by
``scripts/synthesize_profiles.py``. Drop a new captured profile directory in
(see ``scripts/capture_fixtures.py``) and the whole suite runs against it with
no code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from gli4py.enums import TailscaleConnection
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use Home Assistant's snapshot serializer (states, registry entries)."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@dataclass(frozen=True)
class Profile:
    """A captured (or synthesized) router profile and its expectations."""

    id: str
    directory: Path
    manifest: dict[str, Any]

    def load(self, name: str) -> Any | None:
        """Return an endpoint fixture, or None when this profile omits it."""
        path = self.directory / f"{name}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def factory_mac(self) -> str:
        """Return the router's sanitised factory MAC (the entry unique_id)."""
        return self.manifest["factory_mac"]


def load_profile(profile_id: str) -> Profile:
    """Load a single profile by directory id (for non-parametrized tests)."""
    directory = FIXTURES / profile_id
    manifest = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
    return Profile(profile_id, directory, manifest)


def _discover_profiles() -> list[str]:
    """Return the matrix profile ids (those a healthy setup can load).

    Profiles flagged ``expect_setup_crash`` reproduce a real crash and would
    blow up every test, so they are excluded from the matrix and exercised by a
    dedicated regression test instead.
    """
    ids = []
    for path in sorted(FIXTURES.iterdir()):
        manifest = path / "profile.json"
        if not manifest.is_file():
            continue
        if json.loads(manifest.read_text(encoding="utf-8")).get("expect_setup_crash"):
            continue
        ids.append(path.name)
    return ids


@pytest.fixture(params=_discover_profiles())
def profile(request: pytest.FixtureRequest) -> Profile:
    """Parametrized router profile; consuming tests run once per profile."""
    return load_profile(request.param)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,  # noqa: ARG001  (pthcc fixture)
) -> None:
    """Enable loading the glinet custom integration in every test."""
    return


@pytest.fixture
def entity_registry_enabled_by_default() -> Any:
    """Force every entity (incl. disabled-by-default trackers) to be enabled.

    ``ScannerEntity`` device trackers and the Tailscale switch are disabled by
    default, but snapshot_platform asserts every entity is enabled, so patch the
    default on both the base entity and ScannerEntity. Must wrap setup, so
    request it before the integration is configured.
    """
    with (
        patch(
            "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "homeassistant.components.device_tracker.config_entry."
            "ScannerEntity.entity_registry_enabled_default",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
def mock_config_entry(profile: Profile) -> MockConfigEntry:
    """Return a mock config entry built from the active profile's manifest."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=profile.manifest["title"],
        unique_id=profile.factory_mac,
        data={
            CONF_HOST: "http://192.168.8.1",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "test-password",
            CONF_API_TOKEN: "test-token",
        },
        options={CONF_CONSIDER_HOME: 180},
    )


def build_mock_api(profile: Profile) -> AsyncMock:
    """Build an AsyncMock GLinet client backed by a profile's fixtures.

    Endpoints a profile omits are coerced to the *type the real client returns*
    (``{}`` / ``[]`` / ``False`` / ``DISCONNECTED``). This matters: an unset
    AsyncMock attribute returns a truthy child mock, which would make a
    feature-absent profile silently pass on garbage instead of exercising the
    real "feature absent" code path.
    """
    api = AsyncMock()
    api.router_info.return_value = profile.load("router_info")
    api.router_get_status.return_value = profile.load("router_get_status")
    api.connected_clients.return_value = profile.load("connected_clients") or {}
    api.wifi_ifaces_get.return_value = profile.load("wifi_ifaces_get") or {}

    endpoints = profile.manifest.get("endpoints", {})
    api.tailscale_configured.return_value = endpoints.get("tailscale_configured", False)
    api._tailscale_get_config.return_value = profile.load("tailscale_get_config") or {}
    connection_state = endpoints.get("tailscale_connection_state", "DISCONNECTED")
    api.tailscale_connection_state.return_value = TailscaleConnection[connection_state]

    api.wireguard_client_list.return_value = profile.load("wireguard_client_list") or []
    api.wireguard_client_state.return_value = (
        profile.load("wireguard_client_state") or []
    )

    # Action endpoints (no useful return value).
    api.router_reboot.return_value = None
    api.wifi_iface_set_enabled.return_value = None
    api.tailscale_start.return_value = None
    api.tailscale_stop.return_value = None
    api.wireguard_client_start.return_value = None
    api.wireguard_client_stop.return_value = None
    api.logged_in = True
    return api


@pytest.fixture
def mock_api(profile: Profile) -> AsyncMock:
    """Return a fresh mock GLinet API client for the active profile."""
    return build_mock_api(profile)


@pytest.fixture
def mock_glinet(mock_api: AsyncMock) -> AsyncMock:
    """Patch the GLinet client used by the coordinator to the mock API."""
    with patch("custom_components.glinet.coordinator.GLinet", return_value=mock_api):
        yield mock_api


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> MockConfigEntry:
    """Set up the glinet integration with mocked API and return the entry."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
