"""Base entity class for the GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import GLinetDataUpdateCoordinator

if TYPE_CHECKING:
    from .router import GLinetRouter


class GLinetEntity(CoordinatorEntity[GLinetDataUpdateCoordinator]):
    """Base class for GL-iNet entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GLinetDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.router: GLinetRouter = coordinator.router
        self._attr_device_info = coordinator.router.device_info
