"""Button platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button entities."""
    async_add_entities([RebootButton(entry.runtime_data)])


class RebootButton(CoordinatorEntity["GLinetUpdateCoordinator"], ButtonEntity):
    """Reboot button."""

    _attr_icon = "mdi:restart"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize a GLinet device."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"glinet_button/{coordinator.factory_mac}/reboot"

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return "Reboot"

    async def async_press(self) -> None:
        """Reboot the router."""
        await self.coordinator.api.router_reboot()
