"""Tests for the GL-iNet integration setup and unload."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from gli4py.error_handling import AuthenticationError, TokenError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet import async_remove_config_entry_device
from custom_components.glinet.const import DOMAIN
from custom_components.glinet.coordinator import (
    GLinetRuntimeData,
    GLinetStatusCoordinator,
    GLinetSwitchCoordinator,
)
from custom_components.glinet.router import GLinetRouter
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)


async def test_setup_entry_ok(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a successful setup creates entities on all platforms."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert isinstance(init_integration.runtime_data, GLinetRuntimeData)
    assert isinstance(init_integration.runtime_data.router, GLinetRouter)
    assert isinstance(
        init_integration.runtime_data.coordinator, GLinetStatusCoordinator
    )
    assert isinstance(
        init_integration.runtime_data.switch_coordinator, GLinetSwitchCoordinator
    )

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


async def test_setup_entry_token_error_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a token error during setup puts the entry in retry state, not auth error."""
    mock_api.login.side_effect = TokenError("session expired or invalid")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


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
    router: GLinetRouter = init_integration.runtime_data.router
    assert router._consider_home == pytest.approx(60)


async def test_default_password_creates_repair_issue(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test using default password creates a repair issue."""
    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "default_password")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING


async def test_custom_password_clears_repair_issue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test using non-default password does not create a repair issue."""
    orig_login = mock_api.login._mock_wraps

    async def _fake_login(user: str, pwd: str) -> None:
        await orig_login(user, "goodlife")

    mock_api.login.side_effect = _fake_login
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_PASSWORD: "custompassword"},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "default_password")
    assert issue is None


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test async_remove_config_entry_device allows deleting a device."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, "test_device")},
    )

    assert await async_remove_config_entry_device(hass, init_integration, device_entry)
