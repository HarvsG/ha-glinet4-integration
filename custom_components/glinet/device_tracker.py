"""Support for GLinet routers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import TRACK_RANDOMIZED_MAC_ENABLED
from .utils import is_randomized_mac

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .router import ClientDevInfo, GLinetRouter

DEFAULT_DEVICE_NAME = "Unknown device"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up device tracker for GLinet component."""
    router: GLinetRouter = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def update_router() -> None:
        """Update the values of the router."""
        add_entities(router, async_add_entities, tracked)

    # Create entities for any devices discovered on subsequent polls, not just
    # those present at setup. Without this, new devices were only added on a
    # reload of the integration (issue #139).
    entry.async_on_unload(
        async_dispatcher_connect(hass, router.signal_device_new, update_router)
    )

    update_router()


_LOGGER = logging.getLogger(__name__)


@callback
def add_entities(
    router: GLinetRouter,
    async_add_entities: AddConfigEntryEntitiesCallback,
    tracked: set[str],
) -> None:
    """Add all new tracker entities from the router."""
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

    _attr_source_type: SourceType = SourceType.ROUTER

    def __init__(self, router: GLinetRouter, device: ClientDevInfo) -> None:
        """Initialize a GLinet device."""
        self._router: GLinetRouter = router
        self._device: ClientDevInfo = device
        self._icon = "mdi:radar"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.mac

    @property
    def icon(self) -> str:
        """Icon."""
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
    def entity_registry_enabled_default(self) -> bool:
        """Decide whether a new tracker is enabled by default.

        Randomized-MAC clients honour the ``track_randomized_mac`` option: only
        ``enabled`` turns them on by default (``ignore`` stops the entity being
        created at all - handled in the router). For every other client we
        defer to Home Assistant's ScannerEntity heuristic, which enables a
        tracker only when its MAC maps to a known device and otherwise leaves
        it disabled to avoid surfacing unknown floating MACs.
        """
        if is_randomized_mac(self._device.mac):
            return self._router.randomized_mac_mode == TRACK_RANDOMIZED_MAC_ENABLED
        return super().entity_registry_enabled_default

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes."""

        attrs = {}

        attrs["interface_type"] = str(self._device.interface_type)
        attrs["mac_randomized"] = is_randomized_mac(self._device.mac)
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
    def mac_address(self) -> str | None:
        """Return the mac address of the device."""
        return self._device.mac

    @property
    def should_poll(self) -> bool:
        """State is pushed via the router's dispatcher signal, not polled."""
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
