"""The GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, GLINET_DEFAULT_PW
from .coordinator import (
    GLinetRuntimeData,
    GLinetStatusCoordinator,
    GLinetSwitchCoordinator,
)
from .router import GLinetRouter

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr

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

    status_coordinator = GLinetStatusCoordinator(hass, entry, router)
    switch_coordinator = GLinetSwitchCoordinator(hass, entry, router)

    entry.runtime_data = GLinetRuntimeData(
        router=router,
        coordinator=status_coordinator,
        switch_coordinator=switch_coordinator,
    )

    await status_coordinator.async_config_entry_first_refresh()
    await switch_coordinator.async_config_entry_first_refresh()

    if entry.data.get(CONF_PASSWORD) == GLINET_DEFAULT_PW:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "default_password",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="default_password",
            translation_placeholders={"host": router.host},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "default_password")

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
    _: HomeAssistant, __: GLinetConfigEntry, ___: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True
