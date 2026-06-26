"""The GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .coordinator import GLinetUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import GlinetConfigEntry

PLATFORMS = ["button", "device_tracker", "sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: GlinetConfigEntry) -> bool:
    """Set up GL-iNet from a config entry.

    Called by home assistant on initial config, restart and
    component reload.
    """
    coordinator = GLinetUpdateCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlinetConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator's polling timer is owned by Home Assistant and torn down
    automatically with the config entry, so only the platforms need unloading.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
