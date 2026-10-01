"""Support for GLinet routers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import TRACK_RANDOMIZED_MAC_DISABLED, TRACK_RANDOMIZED_MAC_ENABLED
from .coordinator import GLinetConfigEntry, GLinetStatusCoordinator
from .utils import is_randomized_mac

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from .router import ClientDevInfo

DEFAULT_DEVICE_NAME = "Unknown device"

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _: HomeAssistant,
    entry: GLinetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up device tracker for GLinet component."""
    coordinator: GLinetStatusCoordinator = entry.runtime_data.coordinator
    tracked: set[str] = set()

    @callback
    def _check_new_devices() -> None:
        """Add new devices."""
        new_tracked = []
        for mac, device in coordinator.router.devices.items():
            if mac in tracked:
                continue

            new_tracked.append(GLinetDevice(coordinator, device, tracked))
            tracked.add(mac)

        if new_tracked:
            async_add_entities(new_tracked)

    entry.async_on_unload(coordinator.async_add_listener(_check_new_devices))
    _check_new_devices()


# Device tracker entities represent client devices, not the router itself,
# so they must NOT inherit GLinetEntity (which sets device_info to the
# router). Home Assistant expects tracker entities to stand alone without
# a parent device_info binding.
class GLinetDevice(CoordinatorEntity[GLinetStatusCoordinator], ScannerEntity):
    """Representation of a GLinet tracked device."""

    _attr_source_type: SourceType = SourceType.ROUTER

    def __init__(
        self,
        coordinator: GLinetStatusCoordinator,
        device: ClientDevInfo,
        tracked: set[str] | None = None,
    ) -> None:
        """Initialize a GLinet device."""
        super().__init__(coordinator)
        self.router = coordinator.router
        self._device: ClientDevInfo = device
        self._tracked: set[str] | None = tracked
        self._icon = "mdi:radar"
        self._is_randomized = is_randomized_mac(self._device.mac)
        self._attr_mac_address: str = self._device.mac
        self._attr_unique_id: str = self._device.mac

    async def async_added_to_hass(self) -> None:
        """Handle entity addition to hass."""
        await super().async_added_to_hass()
        if (tracked := self._tracked) is not None:
            self.async_on_remove(lambda: tracked.discard(self._attr_mac_address))

    @property
    def icon(self) -> str:
        """Icon."""
        return self._icon

    @property
    def name(self) -> str:
        """Return the name."""
        return self.hostname

    @property
    def is_connected(self) -> bool:
        """Return true if the device is connected to the network."""
        return self._device.is_connected

    @property
    def extra_state_attributes(self) -> dict[str, StateType | bool]:
        """Return the attributes."""
        attrs: dict[str, StateType | bool] = {
            "interface_type": str(self._device.interface_type),
            "mac_randomized": self._is_randomized,
        }
        if self._device.last_activity:
            attrs["last_time_reachable"] = self._device.last_activity.isoformat(
                timespec="seconds"
            )
        return attrs

    @property
    def hostname(self) -> str:
        """Return the hostname of device."""
        return self._device.name or DEFAULT_DEVICE_NAME

    @property
    def ip_address(self) -> str | None:
        """Return the primary ip address of the device."""
        return self._device.ip_address

    @property
    def mac_address(self) -> str:
        """Return the mac address of the device."""
        return self._device.mac

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if entity is enabled by default."""
        if self._is_randomized:
            if self.router.randomized_mac_mode == TRACK_RANDOMIZED_MAC_ENABLED:
                return True
            if self.router.randomized_mac_mode == TRACK_RANDOMIZED_MAC_DISABLED:
                return False
        return super().entity_registry_enabled_default

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update state when coordinator refreshes."""
        if self._device.mac in self.router.devices:
            self._device = self.router.devices[self._device.mac]
        super()._handle_coordinator_update()
