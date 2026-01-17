"""The GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DATA_GLINET, DOMAIN
from .router import GLinetRouter

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = ["button", "device_tracker", "sensor", "switch", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GL-iNet from a config entry.

    Called by home assistant on initial config, restart and
    component reload.
    """

    # Store an API object for platforms to access
    router = GLinetRouter(hass, entry)
    await router.setup()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {DATA_GLINET: router}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update when config_entry options update."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]

    # Currently router.update_options() never returns True
    if router.update_options(dict(entry.options)):
        await hass.config_entries.async_reload(entry.entry_id)
