"""Sensors for GL-iNet component."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

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
from homeassistant.util import dt as dt_util

from .wan import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_FAILING,
    friendly_name,
    state_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from gli4py.types import SystemStatusMetrics

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .const import StateAttributeValue
    from .router import GLinetConfigEntry, GLinetRouter

_LOGGER = logging.getLogger(__name__)


class SystemStatusEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a GL-iNet system status sensor entity."""

    value_fn: Callable[[SystemStatusMetrics], int | float | None]
    extra_attributes_fn: (
        Callable[[SystemStatusMetrics], dict[str, StateAttributeValue]] | None
    ) = None


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
            cpu.get("temperature") if (cpu := system_status.get("cpu")) else None
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
            la[0]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 0
            else None
        ),
    ),
    SystemStatusEntityDescription(
        key="load_avg5",
        translation_key="load_avg5",
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
        translation_key="load_avg15",
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
    hass: HomeAssistant,
    entry: GLinetConfigEntry,
    async_add_entities: AddEntitiesCallback,
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

    await _setup_wan_sensors(hass, entry, router, async_add_entities)


async def _setup_wan_sensors(
    hass: HomeAssistant,
    entry: GLinetConfigEntry,
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
        persisted_interfaces.add(reg_entry.unique_id[len(wan_unique_id_prefix) :])

    currently_up = {name for name, state in router.wan_status.items() if state.up}

    initial_interfaces = persisted_interfaces | currently_up
    router.register_known_wan_interfaces(initial_interfaces)
    if initial_interfaces:
        async_add_entities(
            [WanStatusSensor(router, iface) for iface in sorted(initial_interfaces)]
        )

    @callback
    def _handle_new_wan(new_interfaces: list[str]) -> None:
        """Add entities for newly-discovered up interfaces."""
        async_add_entities([WanStatusSensor(router, iface) for iface in new_interfaces])

    entry.async_on_unload(
        async_dispatcher_connect(hass, router.signal_wan_new, _handle_new_wan)
    )


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
    def extra_state_attributes(self) -> dict[str, StateAttributeValue] | None:
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
        if (uptime := self.router.system_status.get("uptime")) is None:
            return self._attr_native_value

        if uptime != self._last_uptime:
            self._last_uptime = uptime
            candidate = _derive_boot_time(uptime)
            if _boot_time_changed(self._attr_native_value, candidate):
                self._attr_native_value = candidate
        return self._attr_native_value


_ICON_FOR_WAN_STATE: dict[str, str] = {
    STATE_CONNECTED: "mdi:lan-connect",
    STATE_FAILING: "mdi:lan-disconnect",
    STATE_DISCONNECTED: "mdi:lan-pending",
}


class WanStatusSensor(SensorEntity):
    """Sensor showing the connectivity state of one WAN interface."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATE_CONNECTED, STATE_FAILING, STATE_DISCONNECTED]
    _attr_translation_key = "wan_status"

    def __init__(self, router: GLinetRouter, interface: str) -> None:
        """Initialise a WAN status sensor for the given interface name."""
        self._router = router
        self._interface = interface
        self._attr_unique_id = f"glinet_sensor/{router.factory_mac}/wan_{interface}"
        self._attr_name = friendly_name(interface)
        self._attr_device_info = router.device_info

    @property
    def available(self) -> bool:
        """Return True when the router is reachable."""
        return self._router.available

    @property
    def native_value(self) -> str:
        """Return one of connected / failing / disconnected."""
        state = self._router.wan_status.get(self._interface)
        if state is None:
            return STATE_DISCONNECTED
        return state_for(up=state.up, online=state.online)

    @property
    def icon(self) -> str:
        """Pick an mdi icon based on the current state."""
        return _ICON_FOR_WAN_STATE.get(self.native_value, "mdi:lan-pending")

    @property
    def extra_state_attributes(self) -> dict[str, StateAttributeValue]:
        """Expose raw interface name and link-layer state."""
        state = self._router.wan_status.get(self._interface)
        return {
            "interface": self._interface,
            "up": state.up if state else False,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to the router's per-poll WAN-update signal."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._router.signal_wan_update,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Re-render this entity's state."""
        self.async_write_ha_state()
