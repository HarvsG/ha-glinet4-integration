# custom_components/glinet/binary_sensor.py

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfInformation
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN
from .router import GLinetRouter
from gli4py.interfaces import InterfaceInfo, MultiWANMode, MultiWANState
from gli4py.modem import CellInfo

IFACE_LABELS: dict[str, str] = {
    "modem_0001": "Cellular",
    "wan": "Ethernet 1",
    "wwan": "Repeater",
    "secondwan": "Ethernet 2",
    "tethering": "Tethering",
}

LOGGER = logging.getLogger(__name__)


class GLinetInterfaceConnectivity(BinarySensorEntity):
    """Connectivity for a single GL-iNet Multi-WAN interface."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True

    def __init__(
        self,
        router: GLinetRouter,
        iface_name: str,
        label: str,
        prefer_ipv6: bool = False,
    ) -> None:
        self._router = router
        self._iface_name = iface_name
        self._prefer_ipv6 = prefer_ipv6

        parent_id = router.entry.unique_id or router.factory_mac
        self._attr_unique_id = f"{parent_id}_iface_{iface_name}_connectivity"
        self._attr_name = f"{label} connectivity"

        # Attach to the *child* device
        self._attr_device_info = router.interface_device_info(
            iface_name=iface_name,
            iface_label=label,
        )

    # ------------------------------------------------------------------
    # Convenience: current MultiWAN / interface object
    # ------------------------------------------------------------------
    @property
    def _mwan_state(self) -> MultiWANState | None:
        return self._router.iface_state

    @property
    def _iface(self) -> InterfaceInfo | None:
        state = self._mwan_state
        if not state:
            return None
        return state.interfaces.get(self._iface_name)

    # ------------------------------------------------------------------
    # HA state
    # ------------------------------------------------------------------
    @property
    def is_on(self) -> bool | None:
        """Return True if this interface is considered 'online'."""

        iface = self._iface
        if not iface:
            return None
        return iface.is_online(prefer_ipv6=self._prefer_ipv6)

    async def async_update(self) -> None:
        """Refresh interface state from the router."""

        await self._router.update_interfaces_state()


class GLinetInterfaceSensor(SensorEntity):
    """Diagnostic sensor for a GL-iNet Multi-WAN interface detail."""

    _attr_has_entity_name = True
    _attr_state_class: SensorStateClass | None = None
    _attr_device_class: SensorDeviceClass | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        router: GLinetRouter,
        iface_name: str,
        label: str,
        name_suffix: str,
        value_fn: Callable[[MultiWANState, InterfaceInfo], Any],
        icon: str | None = None,
        native_unit_of_measurement: str | None = None,
        state_class: SensorStateClass | None = None,
        device_class: SensorDeviceClass | None = None,
        entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
        enabled_by_default: bool = True,
    ) -> None:
        self._router = router
        self._iface_name = iface_name
        self._value_fn = value_fn
        self._name_suffix = name_suffix

        parent_id = router.entry.unique_id or router.factory_mac
        self._attr_unique_id = f"{parent_id}_iface_{iface_name}_{name_suffix}"
        self._attr_name = f"{label} {name_suffix.replace('_', ' ')}"
        self._attr_icon = icon
        self._attr_device_info = router.interface_device_info(
            iface_name=iface_name,
            iface_label=label,
        )
        self._attr_native_unit_of_measurement = native_unit_of_measurement
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category
        self._attr_entity_registry_enabled_default = enabled_by_default

    @property
    def _mwan_state(self) -> MultiWANState | None:
        return self._router.iface_state

    @property
    def _iface(self) -> InterfaceInfo | None:
        state = self._mwan_state
        if not state:
            return None
        return state.interfaces.get(self._iface_name)

    @property
    def native_value(self) -> Any:
        state = self._mwan_state
        iface = self._iface
        if not state or not iface:
            return None
        return self._value_fn(state, iface)


def build_interface_sensors(
    router: GLinetRouter, iface: InterfaceInfo, label: str, mode: MultiWANMode
) -> list[GLinetInterfaceSensor]:
    """Create per-interface diagnostic sensors mirroring former attributes."""

    sensors: list[GLinetInterfaceSensor] = []

    iface_name = iface.name

    if mode == MultiWANMode.FAILOVER:
        sensors.append(
            GLinetInterfaceSensor(
                router=router,
                iface_name=iface_name,
                label=label,
                name_suffix="metric",
                value_fn=lambda _state, iface: iface.metric,
                icon="mdi:counter",
                enabled_by_default=False,
            )
        )
    if mode == MultiWANMode.LOAD_BALANCING:
        sensors.append(
            GLinetInterfaceSensor(
                router=router,
                iface_name=iface_name,
                label=label,
                name_suffix="weight",
                value_fn=lambda _state, iface: iface.weight,
                icon="mdi:weight",
            )
        )

    if iface.modem:
        def _cell_entry(iface: InterfaceInfo) -> CellInfo | None:
            """Return the best matching cell info entry for this modem."""

            cells = (
                iface.modem.status.cells_info
                if iface.modem and iface.modem.status
                else None
            )
            if not cells:
                return None

            serving_lte = next(
                (
                    cell
                    for cell in cells
                    if cell.type == "servingcell"
                    and cell.mode
                    and "LTE" in cell.mode.upper()
                ),
                None,
            )
            serving_nr = next(
                (
                    cell
                    for cell in cells
                    if cell.type == "servingcell"
                    and cell.mode
                    and "NR" in cell.mode.upper()
                ),
                None,
            )
            if serving_nr:
                fallback = serving_lte or next(
                    (cell for cell in cells if cell.type == "servingcell"), None
                )
                return _merge_cells(serving_nr, fallback)

            serving = next((cell for cell in cells if cell.type == "servingcell"), None)
            return serving

        def _cell_value(
            fn: Callable[[CellInfo], Any]
        ) -> Callable[[MultiWANState, InterfaceInfo], Any]:
            def _inner(_state: MultiWANState, iface: InterfaceInfo) -> Any:
                cell = _cell_entry(iface)
                if not cell:
                    return None
                return fn(cell)

            return _inner

        def add_sensor(
            name_suffix: str,
            value_fn: Callable[[MultiWANState, InterfaceInfo], Any],
            *,
            icon: str | None = None,
            native_unit_of_measurement: str | None = None,
            state_class: SensorStateClass | None = None,
            device_class: SensorDeviceClass | None = None,
            entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
            enabled_by_default: bool = True,
        ) -> None:
            """Add a modem sensor only when it currently has a value."""

            try:
                current_value = value_fn(None, iface)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                current_value = None
            if current_value is None:
                return
            sensors.append(
                GLinetInterfaceSensor(
                    router=router,
                    iface_name=iface_name,
                    label=label,
                    name_suffix=name_suffix,
                    value_fn=value_fn,
                    icon=icon,
                    native_unit_of_measurement=native_unit_of_measurement,
                    state_class=state_class,
                    device_class=device_class,
                    entity_category=entity_category,
                    enabled_by_default=enabled_by_default,
                )
            )

        add_sensor(
            "modem_connection",
            lambda _state, iface: iface.modem.status.connection_state.name.lower()
            if iface.modem
            and iface.modem.status
            and iface.modem.status.connection_state is not None
            else None,
            icon="mdi:cellphone-wireless",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_signal_strength",
            lambda _state, iface: iface.modem.status.signal.strength.name.lower()
            if iface.modem
            and iface.modem.status
            and iface.modem.status.signal
            and iface.modem.status.signal.strength is not None
            else None,
            icon="mdi:signal-cellular-3",
            entity_category=None,
        )
        add_sensor(
            "modem_mode",
            lambda _state, iface: _modem_mode(iface),
            icon="mdi:cellphone-wireless",
            entity_category=None,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_rssi",
            lambda _state, iface: _as_int(
                iface.modem.status.signal.rssi
                if iface.modem and iface.modem.status and iface.modem.status.signal
                else None
            ),
            icon="mdi:signal",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_rsrp",
            lambda _state, iface: _as_int(
                iface.modem.status.signal.rsrp
                if iface.modem and iface.modem.status and iface.modem.status.signal
                else None
            ),
            icon="mdi:signal",
            native_unit_of_measurement="dBm",
            state_class=SensorStateClass.MEASUREMENT,
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_rsrq",
            lambda _state, iface: _as_int(
                iface.modem.status.signal.rsrq
                if iface.modem and iface.modem.status and iface.modem.status.signal
                else None
            ),
            icon="mdi:signal",
            native_unit_of_measurement="dB",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_ecio",
            lambda _state, iface: _as_int(
                iface.modem.status.signal.ecio
                if iface.modem and iface.modem.status and iface.modem.status.signal
                else None
            ),
            icon="mdi:signal",
            native_unit_of_measurement="dB",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_sinr",
            lambda _state, iface: _as_int(
                iface.modem.status.signal.sinr
                if iface.modem and iface.modem.status and iface.modem.status.signal
                else None
            ),
            icon="mdi:signal",
            native_unit_of_measurement="dB",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_tower_network",
            _cell_value(lambda cell: cell.mode),
            icon="mdi:radio-tower",
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        add_sensor(
            "modem_tower_band",
            _cell_value(lambda cell: _as_int(cell.band)),
            icon="mdi:cellphone-wireless",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_tower_bandwidth",
            _cell_value(lambda cell: cell.dl_bandwidth or cell.ul_bandwidth),
            icon="mdi:chart-bell-curve-cumulative",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_tower_frequency",
            _cell_value(lambda cell: _as_int(cell.tx_channel)),
            icon="mdi:waves-arrow-up",
            native_unit_of_measurement="MHz",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_tower_cell_id",
            _cell_value(lambda cell: cell.id),
            icon="mdi:identifier",
            entity_category=EntityCategory.DIAGNOSTIC,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_traffic_total",
            lambda _state, iface: _as_int(
                iface.modem.status.network.traffic_total
                if iface.modem
                and iface.modem.status
                and iface.modem.status.network
                else None
            ),
            icon="mdi:chart-areaspline",
            native_unit_of_measurement=UnitOfInformation.BYTES,
            state_class=SensorStateClass.TOTAL_INCREASING,
            device_class=SensorDeviceClass.DATA_SIZE,
            entity_category=None,
            enabled_by_default=False,
        )
        add_sensor(
            "modem_ipv4",
            lambda _state, iface: iface.modem.status.network.ipv4.ip
            if iface.modem
            and iface.modem.status
            and iface.modem.status.network
            and iface.modem.status.network.ipv4
            else None,
            icon="mdi:ip",
            entity_category=None,
        )
        add_sensor(
            "modem_ipv4_gateway",
            lambda _state, iface: iface.modem.status.network.ipv4.gateway
            if iface.modem
            and iface.modem.status
            and iface.modem.status.network
            and iface.modem.status.network.ipv4
            else None,
            icon="mdi:router-network",
            enabled_by_default=False,
        )
        add_sensor(
            "modem_ipv4_netmask",
            lambda _state, iface: iface.modem.status.network.ipv4.netmask
            if iface.modem
            and iface.modem.status
            and iface.modem.status.network
            and iface.modem.status.network.ipv4
            else None,
            icon="mdi:subnet",
            enabled_by_default=False,
        )
        add_sensor(
            "modem_ipv4_dns",
            lambda _state, iface: ", ".join(iface.modem.status.network.ipv4.dns)
            if iface.modem
            and iface.modem.status
            and iface.modem.status.network
            and iface.modem.status.network.ipv4
            and iface.modem.status.network.ipv4.dns
            else None,
            icon="mdi:dns",
            enabled_by_default=False,
        )
        add_sensor(
            "sim_operator",
            lambda _state, iface: iface.modem.status.sim_operator
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:sim",
            entity_category=None,
        )
        add_sensor(
            "sim_iccid",
            lambda _state, iface: iface.modem.status.sim_iccid
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:sim",
            enabled_by_default=False,
        )
        add_sensor(
            "sim_phone_number",
            lambda _state, iface: iface.modem.status.sim_phone_number
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:phone",
        )
        add_sensor(
            "sim_mcc",
            lambda _state, iface: iface.modem.status.sim_mcc
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:sim",
            enabled_by_default=False,
        )
        add_sensor(
            "sim_mnc",
            lambda _state, iface: iface.modem.status.sim_mnc
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:sim",
            enabled_by_default=False,
        )
        add_sensor(
            "sim_status",
            lambda _state, iface: iface.modem.status.sim_status.name.lower()
            if iface.modem
            and iface.modem.status
            and iface.modem.status.sim_status is not None
            else None,
            icon="mdi:sim-alert",
            entity_category=None,
        )
        add_sensor(
            "current_sim",
            lambda _state, iface: _format_sim_label(
                iface.modem.status.current_sim if iface.modem and iface.modem.status else None
            ),
            icon="mdi:swap-horizontal",
            entity_category=None,
        )
        add_sensor(
            "sim_auto_switch",
            lambda _state, iface: (
                iface.modem.status.switch_status.name.lower()
                if iface.modem
                and iface.modem.status
                and iface.modem.status.switch_status is not None
                else None
            ),
            icon="mdi:swap-horizontal",
            enabled_by_default=False,
        )
        add_sensor(
            "sms_unread",
            lambda _state, iface: _as_int(
                iface.modem.status.new_sms_count if iface.modem and iface.modem.status else None
            ),
            icon="mdi:message-text",
            state_class=SensorStateClass.MEASUREMENT,
        )
        add_sensor(
            "passthrough_enabled",
            lambda _state, iface: (
                None
                if not iface.modem
                or not iface.modem.status
                or not iface.modem.status.passthrough
                else bool(iface.modem.status.passthrough.get("enable"))
            ),
            icon="mdi:transit-connection-variant",
        )
        add_sensor(
            "passthrough_ip",
            lambda _state, iface: (iface.modem.status.passthrough or {}).get("ip")
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:ip",
        )
        add_sensor(
            "passthrough_gateway",
            lambda _state, iface: (iface.modem.status.passthrough or {}).get("gateway")
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:router-network",
        )
        add_sensor(
            "passthrough_netmask",
            lambda _state, iface: (iface.modem.status.passthrough or {}).get("netmask")
            if iface.modem and iface.modem.status
            else None,
            icon="mdi:subnet",
        )

    return sensors


def _as_int(value: Any) -> int | None:
    """Convert to int when possible."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _modem_mode(iface: InterfaceInfo) -> str | None:
    """Return modem mode and log when missing."""

    if (
        iface.modem
        and iface.modem.status
        and iface.modem.status.signal
        and iface.modem.status.signal.mode is not None
    ):
        return iface.modem.status.signal.mode.label

    LOGGER.debug(
        "Modem mode missing: iface=%s status=%s signal=%s",
        iface.name if hasattr(iface, "name") else None,
        getattr(iface.modem, "status", None) if iface and iface.modem else None,
        getattr(getattr(iface.modem, "status", None), "signal", None)
        if iface and iface.modem
        else None,
    )
    return None


def _merge_cells(primary: CellInfo, fallback: CellInfo | None) -> CellInfo:
    """Return primary cell supplemented with any missing fields from fallback."""

    if not fallback or fallback is primary:
        return primary

    return CellInfo(
        ul_bandwidth=primary.ul_bandwidth or fallback.ul_bandwidth,
        dl_bandwidth=primary.dl_bandwidth or fallback.dl_bandwidth,
        rsrp=primary.rsrp if primary.rsrp is not None else fallback.rsrp,
        id=primary.id or fallback.id,
        rssi=primary.rssi if primary.rssi is not None else fallback.rssi,
        tx_channel=primary.tx_channel or fallback.tx_channel,
        sinr_level=primary.sinr_level
        if primary.sinr_level is not None
        else fallback.sinr_level,
        rsrq_level=primary.rsrq_level
        if primary.rsrq_level is not None
        else fallback.rsrq_level,
        sinr=primary.sinr if primary.sinr is not None else fallback.sinr,
        rsrq=primary.rsrq if primary.rsrq is not None else fallback.rsrq,
        rssi_level=primary.rssi_level
        if primary.rssi_level is not None
        else fallback.rssi_level,
        rsrp_level=primary.rsrp_level
        if primary.rsrp_level is not None
        else fallback.rsrp_level,
        mode=primary.mode or fallback.mode,
        band=primary.band if primary.band is not None else fallback.band,
        type=primary.type or fallback.type,
    )


def _format_sim_label(value: Any) -> str | None:
    """Return SIM label like 'Sim 1' when possible."""

    if (idx := _as_int(value)) is None:
        return None
    return f"Sim {idx}"
