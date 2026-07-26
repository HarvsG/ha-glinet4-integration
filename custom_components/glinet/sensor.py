"""Sensors for GL-iNet component."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .router import GLinetConfigEntry, GLinetRouter

_LOGGER = logging.getLogger(__name__)


class SystemStatusEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a GL-iNet system status sensor entity."""

    value_fn: Callable[[dict], int | float | None]
    extra_attributes_fn: Callable[[dict], dict[str, Any]] | None = None


SYSTEM_SENSORS: list[SystemStatusEntityDescription] = [
    SystemStatusEntityDescription(
        key="cpu_temp",
        translation_key="cpu_temp",
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
        translation_key="load_avg1",
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
        translation_key="load_avg5",
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
        translation_key="load_avg15",
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
        translation_key="memory_use",
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
        translation_key="flash_use",
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
    _: HomeAssistant, entry: GLinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    _LOGGER.debug("Setting up GL-iNet Sensors")

    router = entry.runtime_data
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
                translation_key="uptime",
                icon="mdi:clock",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda a: None,
            ),
        )
    )

    # Filter out sensors this router model doesn't report (e.g. no CPU
    # temperature), but only when we have status data to judge by: if the
    # first poll failed, dropping every sensor would leave them all missing
    # until the entry is reloaded.
    if router.system_status:
        sensors = [sensor for sensor in sensors if sensor.native_value is not None]

    async_add_entities(sensors, True)


def _uptime_calculation(seconds_uptime: float, last_value: datetime | None) -> datetime:
    """Calculate uptime with deviation."""
    delta_uptime: datetime = utcnow() - timedelta(seconds=seconds_uptime)

    if not last_value or abs((delta_uptime - last_value).total_seconds()) > 15:
        return delta_uptime

    return last_value


class GliSensorBase(SensorEntity):
    """GL-iNet sensor base class."""

    _attr_has_entity_name = True

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
    def available(self) -> bool:
        """Return True when the router is reachable."""
        return self.router.available

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
        uptime = self.router.system_status.get("uptime")
        if uptime is None:
            return self._current_value
        self._current_value = _uptime_calculation(uptime, self._current_value)
        return self._current_value
