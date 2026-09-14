"""Tests for the GL-iNet config flow."""

from __future__ import annotations

import ssl
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from gli4py.error_handling import NonZeroResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import (
    CONF_TRACK_RANDOMIZED_MAC,
    DEFAULT_TRACK_RANDOMIZED_MAC,
    DOMAIN,
    TRACK_RANDOMIZED_MAC_ENABLED,
)
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.device_registry import format_mac
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
    assert result["options"] == {CONF_CONSIDER_HOME: 180, CONF_VERIFY_SSL: True}
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
    assert result.get("translation_domain") is None
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
    assert result.get("translation_domain") is None
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
    assert suggested[CONF_VERIFY_SSL] is True
    assert suggested[CONF_TRACK_RANDOMIZED_MAC] == DEFAULT_TRACK_RANDOMIZED_MAC


async def test_user_flow_disable_verify_ssl(
    hass: HomeAssistant, mock_glinet: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    """Test creating an entry with SSL verification disabled."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    user_input = {
        **USER_INPUT,
        CONF_HOST: "https://192.168.8.1",
        CONF_VERIFY_SSL: False,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "https://192.168.8.1"
    assert result["options"][CONF_VERIFY_SSL] is False


async def test_options_flow_updates_verify_ssl(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test updating verify_ssl through the options flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONSIDER_HOME: 180, CONF_VERIFY_SSL: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_VERIFY_SSL] is False


async def test_options_flow_updates_track_randomized_mac(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test updating track_randomized_mac through the options flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CONSIDER_HOME: 180,
            CONF_VERIFY_SSL: True,
            CONF_TRACK_RANDOMIZED_MAC: TRACK_RANDOMIZED_MAC_ENABLED,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (
        mock_config_entry.options[CONF_TRACK_RANDOMIZED_MAC]
        == TRACK_RANDOMIZED_MAC_ENABLED
    )


async def test_reconfigure_flow_disable_verify_ssl(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reconfiguring an entry to update verify_ssl."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Verify suggested values default to existing entry values
    schema = result["data_schema"]
    assert schema is not None
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in schema.schema
    }
    assert suggested[CONF_VERIFY_SSL] is True

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "https://192.168.0.1",
            CONF_PASSWORD: "goodlife",
            CONF_VERIFY_SSL: False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "https://192.168.0.1"
    assert mock_config_entry.options[CONF_VERIFY_SSL] is False

    # Starting reconfigure again should pre-fill verify_ssl from options as False
    result2 = await mock_config_entry.start_reconfigure_flow(hass)
    schema2 = result2["data_schema"]
    assert schema2 is not None
    suggested2 = {
        str(key): (key.description or {}).get("suggested_value")
        for key in schema2.schema
    }
    assert suggested2[CONF_VERIFY_SSL] is False


async def test_connect_ssl_error(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test SSL certificate verification failure produces cannot_connect error."""
    mock_api = mock_glinet.return_value
    ssl_err = ssl.SSLCertVerificationError("self-signed certificate")
    cert_err = aiohttp.ClientConnectorCertificateError(None, ssl_err)  # type: ignore[arg-type]
    mock_api.router_reachable.side_effect = cert_err

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    user_input = {
        **USER_INPUT,
        CONF_HOST: "https://192.168.0.1",
        CONF_VERIFY_SSL: True,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_connect_non_ssl_client_error(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test non-SSL connection error logs exception and produces cannot_connect."""
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.side_effect = aiohttp.ClientConnectionError(
        "Connection refused"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_connect_type_error(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test TypeError on router_reachable produces cannot_connect."""
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.side_effect = TypeError("Unexpected response format")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_authenticate_non_zero_response(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test API returning NonZeroResponse during authentication produces invalid_auth."""
    mock_api = mock_glinet.return_value
    mock_api.logged_in = False
    mock_api.login.side_effect = NonZeroResponse("Authentication error")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_authenticate_router_info_failure(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test API returning NonZeroResponse during router_info produces invalid_auth."""
    mock_api = mock_glinet.return_value
    mock_api.logged_in = True
    mock_api.router_info.side_effect = NonZeroResponse("Router info failed")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_testing_hub_authenticate_router_info_failure(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test TestingHub.authenticate returns False when router_info raises NonZeroResponse."""
    from custom_components.glinet.config_flow import TestingHub  # noqa: PLC0415

    mock_api = mock_glinet.return_value
    mock_api.logged_in = True
    mock_api.router_info.side_effect = NonZeroResponse("Router info failed")

    hub = TestingHub("root", "http://192.168.8.1", hass)
    assert await hub.authenticate("goodlife") is False


async def test_dhcp_flow_already_configured_via_lan_mac(
    hass: HomeAssistant,
) -> None:
    """Test DHCP aborts when an existing entry is configured with the LAN MAC."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet Router",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.8.99",
            CONF_PASSWORD: "goodlife",
        },
        unique_id=format_mac(DHCP_SERVICE_INFO.macaddress),
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DHCP_SERVICE_INFO,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test reauth flow shows cannot_connect when router is unreachable."""
    mock_config_entry.add_to_hass(hass)
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.return_value = False

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PASSWORD: "new_password"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reauth flow handles unexpected exceptions during validation."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.glinet.config_flow.validate_input",
        side_effect=RuntimeError("Unexpected validation failure"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test reconfigure shows cannot_connect when host is unreachable."""
    mock_config_entry.add_to_hass(hass)
    mock_api = mock_glinet.return_value
    mock_api.router_reachable.return_value = False

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.8.1",
            CONF_PASSWORD: "goodlife",
            CONF_VERIFY_SSL: True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
) -> None:
    """Test reconfigure shows invalid_auth on bad credentials."""
    mock_config_entry.add_to_hass(hass)
    mock_api = mock_glinet.return_value
    mock_api.logged_in = False

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "http://192.168.8.1",
            CONF_PASSWORD: "wrong_password",
            CONF_VERIFY_SSL: True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_unknown_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reconfigure handles unexpected exception gracefully."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.glinet.config_flow.validate_input",
        side_effect=RuntimeError("Unexpected error"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "root",
                CONF_HOST: "http://192.168.8.1",
                CONF_PASSWORD: "goodlife",
                CONF_VERIFY_SSL: True,
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_flow_migrates_data_verify_ssl(
    hass: HomeAssistant,
    mock_glinet: MagicMock,
) -> None:
    """Test reconfiguring legacy entry with verify_ssl in data updates both data and options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT6000",
        data={
            CONF_USERNAME: "root",
            CONF_HOST: MOCK_HOST,
            CONF_PASSWORD: "goodlife",
            CONF_VERIFY_SSL: True,
        },
        options={},
        unique_id=MOCK_MAC,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "root",
            CONF_HOST: "https://192.168.0.1",
            CONF_PASSWORD: "goodlife",
            CONF_VERIFY_SSL: False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_VERIFY_SSL] is False
    assert entry.options[CONF_VERIFY_SSL] is False
