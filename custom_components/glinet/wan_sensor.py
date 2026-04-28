"""WAN status sensor entity for the GL-iNet integration.

Lives in its own module (separate from the pure helpers in :mod:`wan`) so
that unit tests for the helpers can run without a Home Assistant harness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .wan import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_FAILING,
    friendly_name,
    state_for,
)

if TYPE_CHECKING:
    from .router import GLinetRouter


_ICON_FOR_STATE: dict[str, str] = {
    STATE_CONNECTED: "mdi:lan-connect",
    STATE_FAILING: "mdi:lan-disconnect",
    STATE_DISCONNECTED: "mdi:lan-pending",
}


class WanStatusSensor(SensorEntity):
    """Sensor showing the connectivity state of one WAN interface."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATE_CONNECTED, STATE_FAILING, STATE_DISCONNECTED]

    def __init__(self, router: GLinetRouter, interface: str) -> None:
        """Initialise a WAN status sensor for the given interface name."""
        self._router = router
        self._interface = interface
        self._attr_unique_id = (
            f"glinet_sensor/{router.factory_mac}/wan_{interface}"
        )
        self._attr_name = friendly_name(interface)
        self._attr_device_info = router.device_info

    @property
    def native_value(self) -> str:
        """Return one of ``connected`` / ``failing`` / ``disconnected``."""
        state = self._router.wan_status.get(self._interface)
        if state is None:
            return STATE_DISCONNECTED
        return state_for(up=state.up, online=state.online)

    @property
    def icon(self) -> str:
        """Pick an mdi icon based on the current state."""
        return _ICON_FOR_STATE[self.native_value]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose raw interface name and link-layer state for automations."""
        state = self._router.wan_status.get(self._interface)
        return {
            "interface": self._interface,
            "up": state.up if state else False,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to the router's per-poll WAN-update signal."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._router.signal_wan_update,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Re-render this entity's state."""
        self.async_write_ha_state()
