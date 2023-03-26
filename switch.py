"""Support for turning on and off Pi-hole system."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DATA_GLINET,
)
from .router import GLinetRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Pi-hole switch."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    if router._wireguard_client_name:
        switches = [
            WireGuardSwitch(
            router,
            router._wireguard_client_name
            )
        ]
        #TODO delte me
        _LOGGER.warning(
                "Wireguard switch entity adding",
            )
        async_add_entities(switches, True)



class WireGuardSwitch(SwitchEntity):
    """Representation of a VPN switch."""
    def __init__(self, router: GLinetRouter, name: str) -> None:
        """Initialize a GLinet device."""
        self._router = router
        self._name = name
    _attr_icon = "mdi:vpn"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f'WG Client {self._name}'

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self._name}/wireguard_client"

    @property
    def is_on(self) -> bool:
        """Return if the service is on."""
        return self._router._wireguard_client_connected

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the service."""
        try:
            await self._router._api.wireguard_client_start(self.name)
            await self._router.update_wireguard_client_state()
        except:
            _LOGGER.error("Unable to enable WG client")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the service."""
        await self._router._api.wireguard_client_stop()
        await self._router.update_wireguard_client_state()
        #TODO handle errors

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        #TODO this should probably be defined in the router device not here in the switch
        data: DeviceInfo = {
            "connections": {(CONNECTION_NETWORK_MAC, self._router._mac)},
            "identifiers": {(DOMAIN, self._router._mac)},
            "name": f'GL-inet {self._router._model.upper()}',
            "model": self._router._model,
            "manufacturer": "GL-inet",
        }
        return data


        return data
