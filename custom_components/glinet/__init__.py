"""The GL-iNet integration."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .router import GLinetRouter
from .utils import adjust_mac

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .router import GLinetConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: GLinetConfigEntry) -> bool:
    """Set up GL-iNet from a config entry.

    Called by home assistant on initial config, restart and
    component reload.
    """

    # Store an API object for platforms to access
    router = GLinetRouter(hass, entry)
    await router.setup()

    entry.runtime_data = router

    entry.async_on_unload(router.unload)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GLinetConfigEntry) -> bool:
    """Unload a config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def update_listener(hass: HomeAssistant, entry: GLinetConfigEntry) -> None:
    """Reload the config entry when its data or options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    _hass: HomeAssistant,
    config_entry: GLinetConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Remove a device from a config entry."""
    router = config_entry.runtime_data

    # Never remove the router device itself
    router_macs = set()
    if router.factory_mac:
        router_macs.add(dr.format_mac(router.factory_mac))
        with suppress(ValueError, TypeError):
            router_macs.add(dr.format_mac(adjust_mac(router.factory_mac, 1)))

    if any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
        return False

    device_macs = {
        dr.format_mac(connection[1])
        for connection in device_entry.connections
        if connection[0] == dr.CONNECTION_NETWORK_MAC
    }

    if not device_macs or any(mac in router_macs for mac in device_macs):
        return False

    # Check if any matching device is currently connected
    for mac, device in router.devices.items():
        if dr.format_mac(mac) in device_macs and device.is_connected:
            return False

    # Prune from in-memory devices
    macs_to_remove = [
        mac for mac in router.devices if dr.format_mac(mac) in device_macs
    ]
    for mac in macs_to_remove:
        router.devices.pop(mac, None)

    return True
