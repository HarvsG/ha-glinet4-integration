"""Support for GLinet routers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import DATA_GLINET, DOMAIN
from .router import ClientDevInfo, GLinetRouter

DEFAULT_DEVICE_NAME = "Unknown device"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up device tracker for GLinet component."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    tracked: set[str] = set()

    @callback
    def update_router():
        """Update the values of the router."""
        add_entities(router, async_add_entities, tracked)

    update_router()


_LOGGER = logging.getLogger(__name__)


@callback
def add_entities(router: GLinetRouter, async_add_entities, tracked):
    """Add new tracker entities from the router."""
    new_tracked = []
    for mac, device in router.devices.items():
        if mac in tracked:
            continue

        new_tracked.append(GLinetDevice(router, device))
        tracked.add(mac)

    if new_tracked:
        async_add_entities(new_tracked)


class GLinetDevice(ScannerEntity):
    """Representation of a GLinet tracked device."""

    def __init__(self, router: GLinetRouter, device: ClientDevInfo) -> None:
        """Initialize a GLinet device."""
        self._router: GLinetRouter = router
        self._device: ClientDevInfo = device
        self._icon = (
            "mdi:radar"  # TODO will need to be replaced with brand logo or similar
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        # TODO do we need to prepend DOMAIN to make this unique or does HA do this already?
        return self._device.mac

    @property
    def icon(self) -> str:
        """Icon."""
        # TODO theoretically HA should give the default device tracker icon
        return self._icon

    @property
    def name(self) -> str:
        """Return the name."""
        return self._device.name or DEFAULT_DEVICE_NAME

    @property
    def is_connected(self) -> bool:
        """Return true if the device is connected to the network."""
        return self._device.is_connected

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.ROUTER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes."""
        attrs = {}
        if self._device.last_activity:
            attrs["last_time_reachable"] = self._device.last_activity.isoformat(
                timespec="seconds"
            )
        return attrs

    @property
    def hostname(self) -> str:
        """Return the hostname of device."""
        return self._device.name

    @property
    def ip_address(self) -> str | None:
        """Return the primary ip address of the device."""
        return self._device.ip_address

    @property
    def mac_address(self) -> str:
        """Return the mac address of the device."""
        return self._device.mac

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information.

        TODO Device tracker entities should not create device registry entries.
        according to HomeAssistant so this will have to remain until merge
        Perhaps an ideal scenario would be to only 'create' a device if it already
        exists
        """
        data: DeviceInfo = {
            "connections": {(CONNECTION_NETWORK_MAC, self._device.mac)},
            "via_device": ((DOMAIN, self._router.factory_mac)),
        }
        if self._device.name:
            data["default_name"] = self._device.name
        return data

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    @callback
    def async_on_demand_update(self) -> None:
        """Update state."""
        self._device = self._router.devices[self._device.mac]
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register state update callback."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._router.signal_device_update,
                self.async_on_demand_update,
            )
        )
