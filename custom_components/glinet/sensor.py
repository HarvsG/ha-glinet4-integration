"""Sensors for GL-inet component."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from .const import DATA_GLINET, DOMAIN
from .router import GLinetRouter

_LOGGER = logging.getLogger(__name__)


class SystemStatusEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a GL-inet system status sensor entity."""

    value_fn: Callable[[dict], int | float | None]


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
        value_fn=lambda system_status: system_status.get("cpu").get("temperature")
        if system_status.get("cpu")
        else None,
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
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    _LOGGER.debug("Setting up GL-inet Sensors")

    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
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


def _uptime_calculation(seconds_uptime: float, last_value: datetime | None) -> datetime:
    """Calculate uptime with deviation."""
    delta_uptime = utcnow() - timedelta(seconds=seconds_uptime)

    if not last_value or abs((delta_uptime - last_value).total_seconds()) > 15:
        return delta_uptime

    return last_value


class GliSensorBase(SensorEntity):
    """GL-inet sensor base class."""

    def __init__(
        self,
        router: GLinetRouter,
        entity_description: SystemStatusEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        self.router = router
        self.entity_description = entity_description
        self._attr_device_info = router.device_info

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_sensor/{self.router.factory_mac}/system_{self.entity_description.key}"


class SystemStatusSensor(GliSensorBase):
    """GL-inet system status sensor class."""

    @property
    def native_value(self) -> int | float | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.router.system_status)


class SystemUptimeSensor(GliSensorBase):
    """GL-inet system uptime sensor class."""

    _current_value = None

    @property
    def native_value(self) -> datetime | None:
        """Return the native value of the sensor."""
        self._current_value = _uptime_calculation(
            self.router.system_status["uptime"], self._current_value
        )
        return self._current_value
