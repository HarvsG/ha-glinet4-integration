"""Sensors for GL-iNet component."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.dt import utcnow

from .wan_sensor import WanStatusSensor

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .router import GLinetRouter

_LOGGER = logging.getLogger(__name__)


class SystemStatusEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a GL-iNet system status sensor entity."""

    value_fn: Callable[[dict], int | float | None]
    extra_attributes_fn: Callable[[dict], dict[str, Any]] | None = None


SYSTEM_SENSORS: list[SystemStatusEntityDescription] = [
    SystemStatusEntityDescription(
        key="cpu_temp",
        name="CPU temperature",
        has_entity_name=True,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda system_status: (
            (cpu := system_status.get("cpu")) and cpu.get("temperature")
        ),
    ),
    SystemStatusEntityDescription(
        key="load_avg1",
        name="Load avg (1m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            (la := system_status.get("load_average")) and isinstance(la, list) and la[0]
        )
        or None,
    ),
    SystemStatusEntityDescription(
        key="load_avg5",
        name="Load avg (5m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            (la := system_status.get("load_average"))
            and isinstance(la, list)
            and len(la) > 1
            and la[1]
        )
        or None,
    ),
    SystemStatusEntityDescription(
        key="load_avg15",
        name="Load avg (15m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            (la := system_status.get("load_average"))
            and isinstance(la, list)
            and len(la) > 2
            and la[2]
        )
        or None,
    ),
    SystemStatusEntityDescription(
        key="memory_use",
        name="Memory usage",
        has_entity_name=True,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda system_status: (
            (memory_total := system_status.get("memory_total", 0)) > 0
            and (memory_free := system_status.get("memory_free", 0)) >= 0
            and (mu := 100 * (1 - memory_free / memory_total))
            and isinstance(mu, float)
            and 0 <= mu <= 100
            and mu
        )
        or None,
        extra_attributes_fn=lambda system_status: {
            "memory_total": system_status.get("memory_total"),
            "memory_free": system_status.get("memory_free"),
        },
    ),
    SystemStatusEntityDescription(
        key="flash_use",
        name="Flash usage",
        has_entity_name=True,
        icon="mdi:harddisk",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda system_status: (
            (flash_total := system_status.get("flash_total", 0)) > 0
            and (flash_free := system_status.get("flash_free", 0)) >= 0
            and (fu := 100 * (1 - flash_free / flash_total))
            and isinstance(fu, float)
            and 0 <= fu <= 100
            and fu
        )
        or None,
        extra_attributes_fn=lambda system_status: {
            "flash_total": system_status.get("flash_total"),
            "flash_free": system_status.get("flash_free"),
        },
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    _LOGGER.debug("Setting up GL-iNet Sensors")

    router: GLinetRouter = entry.runtime_data
    sensors: list[SystemStatusSensor | SystemUptimeSensor] = [
        SystemStatusSensor(router=router, entity_description=description)
        for description in SYSTEM_SENSORS
    ]
    # Special case for uptime as it requires additional data processing
    sensors.append(
        SystemUptimeSensor(
            router=router,
            entity_description=SystemStatusEntityDescription(
                key="uptime",
                name="Uptime",
                has_entity_name=True,
                icon="mdi:clock",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda a: None,
            ),
        )
    )

    for sensor in sensors:
        if sensor.native_value is None:
            sensors.remove(sensor)

    async_add_entities(sensors, True)

    # WAN status sensors: load any persisted entities from the registry,
    # plus an entity per interface currently reporting up. Future "new WAN"
    # discoveries are picked up via the router's dispatcher signal.
    await _setup_wan_sensors(hass, entry, router, async_add_entities)


async def _setup_wan_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    router: GLinetRouter,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register WAN sensors from registry + currently-up interfaces, then subscribe."""
    entity_registry = er.async_get(hass)
    registry_entries = er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    )

    wan_unique_id_prefix = f"glinet_sensor/{router.factory_mac}/wan_"
    persisted_interfaces: set[str] = set()
    for reg_entry in registry_entries:
        if reg_entry.domain != SENSOR_DOMAIN:
            continue
        if not reg_entry.unique_id.startswith(wan_unique_id_prefix):
            continue
        persisted_interfaces.add(reg_entry.unique_id[len(wan_unique_id_prefix):])

    currently_up = {
        name for name, state in router.wan_status.items() if state.up
    }

    initial_interfaces = persisted_interfaces | currently_up
    router.register_known_wan_interfaces(initial_interfaces)
    if initial_interfaces:
        async_add_entities(
            WanStatusSensor(router, iface)
            for iface in sorted(initial_interfaces)
        )

    @callback
    def _handle_new_wan(new_interfaces: list[str]) -> None:
        """Add entities for newly-discovered up interfaces.

        The router fires ``signal_wan_new`` with the sorted list of names
        that just transitioned to ``known``. Each name fires exactly once,
        so we don't need to deduplicate here.
        """
        async_add_entities(
            WanStatusSensor(router, iface) for iface in new_interfaces
        )

    entry.async_on_unload(
        async_dispatcher_connect(hass, router.signal_wan_new, _handle_new_wan)
    )


def _uptime_calculation(seconds_uptime: float, last_value: datetime | None) -> datetime:
    """Calculate uptime with deviation."""
    delta_uptime: datetime = utcnow() - timedelta(seconds=seconds_uptime)

    if not last_value or abs((delta_uptime - last_value).total_seconds()) > 15:
        return delta_uptime

    return last_value


class GliSensorBase(SensorEntity):
    """GL-iNet sensor base class."""

    def __init__(
        self,
        router: GLinetRouter,
        entity_description: SystemStatusEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        self.router = router
        self.entity_description: SystemStatusEntityDescription = entity_description
        self._attr_device_info = router.device_info

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_sensor/{self.router.factory_mac}/system_{self.entity_description.key}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.router.system_status)


class SystemStatusSensor(GliSensorBase):
    """GL-iNet system status sensor class."""

    @property
    def native_value(self) -> int | float | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.router.system_status)


class SystemUptimeSensor(GliSensorBase):
    """GL-iNet system uptime sensor class."""

    _current_value: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        """Return the native value of the sensor."""
        self._current_value = _uptime_calculation(
            self.router.system_status["uptime"], self._current_value
        )
        return self._current_value
