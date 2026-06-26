"""Tests for the GL-iNet config flow."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

USER_INPUT = {
    CONF_USERNAME: "root",
    CONF_HOST: "http://192.168.8.1",
    CONF_PASSWORD: "test-password",
    CONF_CONSIDER_HOME: 180,
}


def _existing_entry() -> MockConfigEntry:
    """Return a configured entry whose stored password is about to be reauthed."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="00:11:22:00:00:01",
        data={
            CONF_HOST: "http://192.168.8.1",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "stale-password",
            CONF_API_TOKEN: "stale-token",
        },
    )


@pytest.fixture
def mock_flow_api() -> Iterator[AsyncMock]:
    """Patch the GLinet client used by the config flow."""
    api = AsyncMock()
    api.router_reachable.return_value = True
    api.router_info.return_value = {CONF_MAC: "00:11:22:00:00:01", "model": "mt6000"}
    api.logged_in = True
    api.sid = "test-token"
    with patch("custom_components.glinet.config_flow.GLinet", return_value=api):
        yield api


async def test_user_flow_success(hass: HomeAssistant, mock_flow_api: AsyncMock) -> None:
    """A valid user flow creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GL-iNet MT6000"
    assert result["data"][CONF_HOST] == "http://192.168.8.1"


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_flow_api: AsyncMock
) -> None:
    """An unreachable router surfaces a cannot_connect error."""
    mock_flow_api.router_reachable.return_value = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_flow_api: AsyncMock
) -> None:
    """Failed authentication surfaces an invalid_auth error."""
    mock_flow_api.logged_in = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_success(
    hass: HomeAssistant, mock_flow_api: AsyncMock
) -> None:
    """A reauth flow re-prompts for the password and refreshes the token."""
    entry = _existing_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "root", CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_API_TOKEN] == "test-token"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant, mock_flow_api: AsyncMock
) -> None:
    """A reauth flow surfaces invalid_auth and lets the user retry."""
    mock_flow_api.logged_in = False
    entry = _existing_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "root", CONF_PASSWORD: "still-wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
