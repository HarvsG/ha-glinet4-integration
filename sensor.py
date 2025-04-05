"""Sensors for GL-inet component."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from .const import DATA_GLINET, DOMAIN
from .router import GLinetRouter

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SystemStatusEntityDescription(SensorEntityDescription):
    """Describes a GL-inet system status sensor entity."""

    value_fn: Callable[[dict], int | float | None]


SYSTEM_SENSORS: tuple[SystemStatusEntityDescription, ...] = (
    SystemStatusEntityDescription(
        key="cpu_temp",
        name="cpu temperature",
        has_entity_name=True,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda system_status: system_status["cpu"]["temperature"],
    ),
    SystemStatusEntityDescription(
        key="load_avg1",
        name="Load avg (1m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: system_status["load_average"][0],
    ),
    SystemStatusEntityDescription(
        key="load_avg5",
        name="Load avg (5m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: system_status["load_average"][1],
    ),
    SystemStatusEntityDescription(
        key="load_avg15",
        name="Load avg (15m)",
        has_entity_name=True,
        icon="mdi:cpu-64-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: system_status["load_average"][2],
    ),
)


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
                name="uptime",
                has_entity_name=True,
                icon="mdi:clock",
                device_class=SensorDeviceClass.TIMESTAMP,
                value_fn=lambda a: None,
            ),
        )
    )

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

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_sensor/{self.router.factory_mac}/system_{self.entity_description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        # TODO this should probably be defined in the router device not here in the switch
        data: DeviceInfo = {
            "connections": {(CONNECTION_NETWORK_MAC, self.router.factory_mac)},
            "identifiers": {(DOMAIN, self.router.factory_mac)},
        }
        return data


class SystemStatusSensor(GliSensorBase):
    """GL-inet system status sensor class."""

    @property
    def native_value(self) -> int | float | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.router._system_status)


class SystemUptimeSensor(GliSensorBase):
    """GL-inet system uptime sensor class."""

    _current_value = None

    @property
    def native_value(self) -> datetime | None:
        """Return the native value of the sensor."""
        self._current_value = _uptime_calculation(
            self.router._system_status["uptime"], self._current_value
        )
        return self._current_value
