"""Support for turning on and off Pi-hole system."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GLINET, DOMAIN
from .router import GLinetRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button entities."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    buttons: list[RebootButton] = []
    buttons.append(RebootButton(router))
    if buttons:
        async_add_entities(buttons, True)


class RebootButton(ButtonEntity):
    """Reboot button."""

    def __init__(self, router: GLinetRouter) -> None:
        """Initialize a GLinet device."""
        self._router = router

    _attr_icon = "mdi:restart"
    _attr_has_entity_name = True

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return "Reboot"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the button."""
        return f"glinet_button/{self._router.factory_mac}/reboot"

    async def async_press(self) -> None:
        """Reboot the router."""
        await self._router.api.router_reboot()

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        # TODO this should probably be defined in the router device not here in the switch
        data: DeviceInfo = {
            "connections": {(CONNECTION_NETWORK_MAC, self._router.factory_mac)},
            "identifiers": {(DOMAIN, self._router.factory_mac)},
        }
        return data
