"""Tests for the GL-iNet config flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import MOCK_HOST, MOCK_LAN_MAC, MOCK_MAC, MOCK_ROUTER_INFO

USER_INPUT = {
    CONF_USERNAME: "root",
    CONF_HOST: MOCK_HOST,
    CONF_PASSWORD: "goodlife",
    CONF_CONSIDER_HOME: 180,
}

DHCP_SERVICE_INFO = DhcpServiceInfo(
    ip="192.168.8.1",
    hostname="gl-mt6000",
    macaddress=MOCK_LAN_MAC,
)


async def test_user_flow_success(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test the full user flow creates an entry with data and options split."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GL-iNet MT6000"
    assert result["data"] == {
        CONF_USERNAME: "root",
        CONF_HOST: MOCK_HOST,
        CONF_PASSWORD: "goodlife",
    }
    assert result["options"] == {CONF_CONSIDER_HOME: 180}
    assert result["result"].unique_id == MOCK_MAC


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test a connection error shows an error and the flow can recover."""
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.return_value = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_api.router_reachable.return_value = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test failed authentication shows an error and the flow can recover."""
    mock_api = mock_glinet.return_value
    mock_api.logged_in = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_api.logged_in = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unknown_error(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test an unexpected exception maps to the unknown error."""
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.side_effect = ValueError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test configuring an already configured router aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_dhcp_flow_success(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test DHCP discovery pre-fills the user form and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The unique id is the factory MAC: the discovered LAN MAC minus one
    assert result["result"].unique_id == MOCK_MAC


async def test_dhcp_flow_cannot_connect_aborts(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test DHCP discovery aborts when the router is not reachable."""
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.return_value = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_dhcp_flow_already_configured_aborts(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test DHCP discovery of an already configured router aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the reauth flow updates only the password."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-password"
    assert mock_config_entry.data[CONF_HOST] == MOCK_HOST
    assert mock_config_entry.data[CONF_USERNAME] == "root"


async def test_reauth_flow_wrong_password_then_success(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the reauth flow re-renders on a wrong password, then succeeds."""
    mock_config_entry.add_to_hass(hass)
    mock_api = mock_glinet.return_value
    mock_api.logged_in = False

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}

    mock_api.logged_in = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "correct-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "correct-password"


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the reconfigure flow updates the connection settings."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.9.1",
            CONF_PASSWORD: "goodlife",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "http://192.168.9.1"


async def test_reconfigure_flow_unique_id_mismatch_aborts(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reconfiguring against a different router aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_api = mock_glinet.return_value
    mock_api.router_info.side_effect = lambda *_args, **_kwargs: {
        **MOCK_ROUTER_INFO,
        "mac": "11:22:33:44:55:66",
    }

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.9.1",
            CONF_PASSWORD: "goodlife",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert mock_config_entry.data[CONF_HOST] == MOCK_HOST


async def test_options_flow(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the options flow updates consider_home."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONSIDER_HOME: 300}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_CONSIDER_HOME] == 300


async def test_options_flow_prefills_from_data_fallback(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test the options form falls back to entry data for legacy entries."""
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "root",
            CONF_HOST: MOCK_HOST,
            CONF_PASSWORD: "goodlife",
            CONF_CONSIDER_HOME: 240,
        },
        options={},
        unique_id=MOCK_MAC,
    )
    legacy_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(legacy_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    schema = result["data_schema"]
    assert schema is not None
    suggested: dict[str, Any] = {
        str(key): (key.description or {}).get("suggested_value")
        for key in schema.schema
    }
    assert suggested[CONF_CONSIDER_HOME] == 240
