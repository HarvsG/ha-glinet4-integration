"""The GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .coordinator import GLinetDataUpdateCoordinator
from .router import GLinetRouter

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import GLinetConfigEntry

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
    router = GLinetRouter(hass, entry)
    await router.setup()

    coordinator = GLinetDataUpdateCoordinator(hass, entry, router)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GLinetConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def update_listener(hass: HomeAssistant, entry: GLinetConfigEntry) -> None:
    """Reload the config entry when its data or options change."""
    await hass.config_entries.async_reload(entry.entry_id)
