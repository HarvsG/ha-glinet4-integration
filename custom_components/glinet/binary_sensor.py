"""Binary sensors for GL-iNet interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GLINET, DOMAIN
from .interface import GLinetInterfaceConnectivity, IFACE_LABELS

if TYPE_CHECKING:
    from .router import GLinetRouter


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up interface connectivity binary sensors."""

    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    await router.update_interfaces_state()

    iface_state = router.iface_state
    if not iface_state:
        return

    entities: list[GLinetInterfaceConnectivity] = []
    for iface_name in iface_state.interfaces:
        label = IFACE_LABELS.get(iface_name, iface_name)
        entities.append(
            GLinetInterfaceConnectivity(
                router=router,
                iface_name=iface_name,
                label=label,
            )
        )

    async_add_entities(entities, True)
