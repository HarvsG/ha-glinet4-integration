"""Config flow for GL-inet integration."""
from __future__ import annotations

import logging
from typing import Any

from gli4py import GLinet
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
)
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac

from .const import API_PATH, DOMAIN, GLINET_DEFAULT_PW, GLINET_DEFAULT_URL, GLINET_DEFAULT_USERNAME

# from homeassistant.helpers import config_validation as cv


_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=GLINET_DEFAULT_USERNAME): str,
        vol.Required(CONF_HOST, default=GLINET_DEFAULT_URL): str,
        vol.Required(CONF_PASSWORD, default=GLINET_DEFAULT_PW): str,
    }
)


class TestingHub:
    """Testing class to test connection and authentication."""

    def __init__(self, username: str, host: str) -> None:
        """Initialize."""
        self.host: str = host
        self.username: str = username
        self.router: GLinet = GLinet(base_url=self.host + API_PATH)
        self.router_mac: str = ""
        self.router_model: str = ""

    async def connect(self) -> bool:
        """Test if we can communicate with the host."""
        try:
            res = await self.router.router_reachable(self.username)
            # TODO, on success we can/should probably store some immutable device info in the class.
            _LOGGER.warn(
                "Attempting to connect to router, success:%s", res
            )
            return res
        except ConnectionError:
            _LOGGER.error(
                "Failed to connect to %s, is it really a GL-inet router?", self.host
            )
        except TypeError:
            _LOGGER.error(
                "Failed to parse router response to %s, is it the right firmware version?",
                self.host,
            )
        return False

    async def authenticate(self, password: str) -> bool:
        """Test if we can authenticate with the host."""
        try:
            await self.router.login(self.username, password)
            res = await self.router.router_info()
            self.router_mac = res["mac"]
            self.router_model = res["model"]
            # TODO, on success we can/should probably store some immutable device info in the class.
        except ConnectionRefusedError:
            _LOGGER.error("Failed to authenticate with Gl-inet router during testing")
        return self.router.logged_in


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    hub = TestingHub(data[CONF_USERNAME], data[CONF_HOST])

    if not await hub.connect():
        raise CannotConnect

    if not await hub.authenticate(data[CONF_PASSWORD]):
        raise InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        # TODO, on success we can/should probably store some immutable device info in the class.
        # TODO should we be using inbuilt literals and consts here?
        "title": "GL-inet " + hub.router_model.capitalize(),
        "mac": hub.router_mac,
        "data": {
            CONF_USERNAME: data[CONF_USERNAME],
            CONF_HOST: data[CONF_HOST],
            CONF_API_TOKEN: hub.router.sid,
            CONF_PASSWORD: data[CONF_PASSWORD],
        },
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GL-inet."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            user_input = {}
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
            )

        errors = {}
        try:
            info = await validate_input(self.hass, user_input)
            # TODO would it be sensible to do some checks here, e.g of API version and issue warnings for possibly unsupported versions?
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            unique_id: str = format_mac(info["mac"])
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=info["data"])

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for GL-inet."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        # TODO add options to reconfigure host name and password
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CONSIDER_HOME,
                    default=self.config_entry.options.get(
                        CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
                    ),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=900))
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
