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
from homeassistant.util import dt as dt_util

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
            la[0]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 0
            else None
        ),
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
            la[1]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 1
            else None
        ),
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
            la[2]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 2
            else None
        ),
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
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
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


# Minimum movement in the derived boot time before a new timestamp is committed
UPTIME_DEVIATION = timedelta(seconds=120)


def _derive_boot_time(seconds_uptime: float) -> datetime:
    """Derive the boot timestamp from the router's uptime counter."""
    now: datetime = dt_util.utcnow()
    return now - timedelta(seconds=seconds_uptime)


def _boot_time_changed(old: datetime | None, new: datetime) -> bool:
    """Return whether the boot time moved enough to warrant a state write."""
    return old is None or abs(new - old) > UPTIME_DEVIATION


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
    """GL-iNet system uptime sensor class.

    The router exposes uptime as a seconds counter, so the boot timestamp is
    derived as ``now - uptime``. It is recomputed only when the router reports a
    fresh uptime value (otherwise reading the property between polls would drift
    the estimate against an advancing clock), and the committed value is held
    stable within ``UPTIME_DEVIATION``.
    """

    _attr_native_value: datetime | None = None
    _last_uptime: float | None = None

    @property
    def native_value(self) -> datetime | None:
        """Return the cached boot timestamp, recomputing only on fresh data."""
        uptime = self.router.system_status["uptime"]
        if uptime != self._last_uptime:
            self._last_uptime = uptime
            candidate = _derive_boot_time(uptime)
            if _boot_time_changed(self._attr_native_value, candidate):
                self._attr_native_value = candidate
        return self._attr_native_value
