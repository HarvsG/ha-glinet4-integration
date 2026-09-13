"""Button platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .router import GLinetConfigEntry, GLinetRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _: HomeAssistant, entry: GLinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button entities."""
    router = entry.runtime_data
    async_add_entities([RebootButton(router)], True)


class RebootButton(ButtonEntity):
    """Reboot button."""

    def __init__(self, router: GLinetRouter) -> None:
        """Initialize a GLinet device."""
        self._router = router
        self._attr_device_info = router.device_info

    _attr_icon = "mdi:restart"
    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART

    @property
    def unique_id(self) -> str:
        """Return the unique id of the button."""
        return f"glinet_button/{self._router.factory_mac}/reboot"

    @property
    def available(self) -> bool:
        """Return True when the router is reachable."""
        return self._router.available

    async def async_press(self) -> None:
        """Reboot the router."""
        await self._router.api.router_reboot()

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG
