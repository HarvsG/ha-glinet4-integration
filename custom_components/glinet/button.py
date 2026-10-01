"""Button platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory

from .coordinator import GLinetStatusCoordinator
from .entity import GLinetEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GLinetConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _: HomeAssistant, entry: GLinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button entities."""
    coordinator: GLinetStatusCoordinator = entry.runtime_data.coordinator
    async_add_entities([RebootButton(coordinator)])


class RebootButton(GLinetEntity[GLinetStatusCoordinator], ButtonEntity):
    """Reboot button."""

    _attr_icon = "mdi:restart"
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: GLinetStatusCoordinator) -> None:
        """Initialize a reboot button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"glinet_button/{self.router.factory_mac}/reboot"

    async def async_press(self) -> None:
        """Reboot the router."""
        await self.router.api.router_reboot()

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG
