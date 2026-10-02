"""Switch platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from gli4py.error_handling import APIClientError
from gli4py.models import PortForwardRule

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .coordinator import GLinetSwitchCoordinator
from .entity import GLinetEntity

if TYPE_CHECKING:
    from gli4py.models import WifiInterface

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from .coordinator import GLinetConfigEntry
    from .router import GLinetRouter, WireGuardClient

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _: HomeAssistant, entry: GLinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up GL-iNet switches."""
    coordinator: GLinetSwitchCoordinator = entry.runtime_data.switch_coordinator
    router: GLinetRouter = coordinator.router
    switches: list[
        WifiApSwitch | WireGuardSwitch | TailscaleSwitch | LedSwitch | PortForwardSwitch
    ] = []
    if router.wireguard_clients:
        switches.extend(
            WireGuardSwitch(coordinator, client)
            for client in router.wireguard_clients.values()
        )
    if router.tailscale_configured:
        switches.append(TailscaleSwitch(coordinator))
    for iface_name, iface in router.wifi_ifaces.items():
        switches.append(WifiApSwitch(coordinator, iface_name, iface))
    if router.led_supported:
        switches.append(LedSwitch(coordinator))
    if switches:
        async_add_entities(switches)

    tracked_port_forward_rules: set[str] = set()

    @callback
    def _check_port_forward_rules() -> None:
        """Add any new port forwarding rule switches."""
        new_switches = []
        for rule_id in router.port_forward_rules:
            if rule_id in tracked_port_forward_rules:
                continue
            new_switches.append(PortForwardSwitch(coordinator, rule_id))
            tracked_port_forward_rules.add(rule_id)
        if new_switches:
            async_add_entities(new_switches)

    _check_port_forward_rules()
    entry.async_on_unload(coordinator.async_add_listener(_check_port_forward_rules))


class GliSwitchBase(GLinetEntity[GLinetSwitchCoordinator], SwitchEntity):
    """GL-inet switch base class."""

    def __init__(self, coordinator: GLinetSwitchCoordinator) -> None:
        """Initialize a GLinet switch."""
        super().__init__(coordinator)
        self._attr_is_on: bool | None = None

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG


class WifiApSwitch(GliSwitchBase):
    """A WiFi AccessPoint switch."""

    def __init__(
        self,
        coordinator: GLinetSwitchCoordinator,
        iface_name: str,
        iface: WifiInterface,
    ) -> None:
        """Initialize a WiFi AP switch."""
        super().__init__(coordinator)
        self._iface_name = iface_name
        self._iface = iface
        self._attr_is_on = iface.enabled

    @property
    def is_on(self) -> bool | None:
        """Return if the AP is on."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        if self.coordinator.data and (
            iface := self.coordinator.data.wifi_ifaces.get(self._iface_name)
        ):
            return bool(iface.enabled)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and (
            iface := self.coordinator.data.wifi_ifaces.get(self._iface_name)
        ):
            self._attr_is_on = iface.enabled
        super()._handle_coordinator_update()

    @property
    def icon(self) -> str:
        """Return AP state icon."""
        if self.is_on:
            return "mdi:wifi"
        return "mdi:wifi-off"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        iface = (
            self.coordinator.data.wifi_ifaces.get(self._iface_name)
            if self.coordinator.data
            else self._iface
        ) or self._iface
        if iface.ssid:
            return iface.ssid
        if iface.name:
            return iface.name
        return self._iface_name

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self.router.factory_mac}/iface_{self._iface_name}"

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        """Return the attributes."""
        iface = (
            self.coordinator.data.wifi_ifaces.get(self._iface_name)
            if self.coordinator.data
            else self._iface
        ) or self._iface
        return {
            "interface": iface.name or self._iface_name,
            "guest": iface.guest,
            "ssid": iface.ssid,
            "hidden": iface.hidden,
            "encryption": iface.encryption,
        }

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the AP."""
        self._attr_is_on = True
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Enabling WiFi interface %s", self._iface_name)
            await self.router.api.wifi_iface_set_enabled(self._iface_name, True)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.exception(
                "Unable to enable WiFi interface %s",
                self._iface_name,
            )

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the AP."""
        # be optimistic
        self._attr_is_on = False
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Disabling WiFi interface %s", self._iface_name)
            await self.router.api.wifi_iface_set_enabled(self._iface_name, False)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.exception(
                "Unable to disable WiFi interface %s",
                self._iface_name,
            )


class TailscaleSwitch(GliSwitchBase):
    """A tailscale switch."""

    _attr_icon = "mdi:vpn"
    _attr_translation_key = "tailscale"

    def __init__(self, coordinator: GLinetSwitchCoordinator) -> None:
        """Initialize Tailscale switch."""
        super().__init__(coordinator)
        if self.coordinator.data:
            self._attr_is_on = self.coordinator.data.tailscale_connection
        else:
            self._attr_is_on = self.router.tailscale_connection

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self.router.factory_mac}/tailscale"

    @property
    def is_on(self) -> bool | None:
        """Return if Tailscale is on."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        if (
            self.coordinator.data
            and (conn := self.coordinator.data.tailscale_connection) is not None
        ):
            return bool(conn)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and (conn := self.coordinator.data.tailscale_connection) is not None
        ):
            self._attr_is_on = conn
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        # be optimistic
        self._attr_is_on = True
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Enabling tailscale")
            await self.router.api.tailscale_start()
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.exception("Unable to enable tailscale connection")

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        # be optimistic
        self._attr_is_on = False
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Disabling tailscale")
            await self.router.api.tailscale_stop()
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.exception("Unable to stop tailscale connection")

    @property
    def extra_state_attributes(self) -> dict[str, StateType | bool]:
        """Return the switch attributes."""
        attrs: dict[str, StateType | bool] = {}
        if self.lan_access is not None:
            attrs["lan_access"] = self.lan_access
        return attrs

    @property
    def lan_access(self) -> bool | None:
        """Whether the router exposes the LAN as a subnet."""
        if not self.router.tailscale_config:
            return None
        return bool(self.router.tailscale_config.lan_enabled)

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enabled by default."""
        return bool(self.router.tailscale_configured)

    @property
    def entity_registry_visible_default(self) -> bool:
        """Enabled by default."""
        return bool(self.router.tailscale_configured)


# TODO make class, client/server/VPN type agnostic and appreciate >1 can be configured of each
# And also appreciates that some combinations of states are not permitted by Gl-inet
# such as can't have a server and a client active of the same VPN type, also can't have
# multiples of any one type etc etc
class WireGuardSwitch(GliSwitchBase):
    """Representation of a VPN switch."""

    def __init__(
        self, coordinator: GLinetSwitchCoordinator, client: WireGuardClient
    ) -> None:
        """Initialize a WireGuard switch."""
        super().__init__(coordinator)
        self._client = client
        self._attr_is_on = client.connected
        self._attr_translation_placeholders = {"client_name": client.name}

    _attr_icon = "mdi:vpn"  # TODO would be better to have MDI style icons for each of the VPN types
    _attr_translation_key = "wireguard_client"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self.router.factory_mac}/{self._client.name}/wireguard_client"

    @property
    def is_on(self) -> bool:
        """Return if WireGuard client is connected."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        if (
            self.coordinator.data
            and self.coordinator.data.wireguard_connections is not None
        ):
            return any(
                c.peer_id == self._client.peer_id
                for c in self.coordinator.data.wireguard_connections
            )
        return self._client in (self.router.connected_wireguard_clients or [])

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.coordinator.data.wireguard_connections is not None
        ):
            self._attr_is_on = any(
                c.peer_id == self._client.peer_id
                for c in self.coordinator.data.wireguard_connections
            )
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        # be optimistic
        self._attr_is_on = True
        self.async_write_ha_state()
        try:
            # TODO Verify that the API doesn't do this for us
            if (
                self._client.tunnel_id
                is None  # This confirms we are using older firmware
                and self.router.connected_wireguard_clients is not None
                and self._client not in self.router.connected_wireguard_clients
            ):
                for client in self.router.connected_wireguard_clients:
                    await self.router.api.wireguard_client_stop(client.peer_id)
                # TODO may need to introduce a delay here, or await confirmation of the stop

            await self.router.api.wireguard_client_start(
                self._client.group_id, self._client.tunnel_id or self._client.peer_id
            )
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.exception("Unable to enable WG client")

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        # be optimistic
        self._attr_is_on = False
        self.async_write_ha_state()
        try:
            await self.router.api.wireguard_client_stop(
                self._client.tunnel_id or self._client.peer_id
            )
            # TODO may need to introduce a delay here, or await confirmation of the stop
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.exception("Unable to stop WG client")


class LedSwitch(GliSwitchBase):
    """A switch to control the router's LED indicators."""

    _attr_translation_key = "led"

    def __init__(self, coordinator: GLinetSwitchCoordinator) -> None:
        """Initialize LED switch."""
        super().__init__(coordinator)
        if self.coordinator.data and self.coordinator.data.led_enabled is not None:
            self._attr_is_on = self.coordinator.data.led_enabled
        else:
            self._attr_is_on = self.router.led_enabled

    @property
    def icon(self) -> str:
        """Return the LED state icon."""
        return "mdi:led-on" if self.is_on else "mdi:led-off"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self.router.factory_mac}/led"

    @property
    def is_on(self) -> bool | None:
        """Return if LED is enabled."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        if self.coordinator.data and self.coordinator.data.led_enabled is not None:
            return bool(self.coordinator.data.led_enabled)
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and self.coordinator.data.led_enabled is not None:
            self._attr_is_on = self.coordinator.data.led_enabled
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the router LEDs."""
        # be optimistic
        self._attr_is_on = True
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Enabling router LEDs")
            await self.router.api.led_set(True)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.exception("Unable to enable router LEDs")

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the router LEDs."""
        # be optimistic
        self._attr_is_on = False
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Disabling router LEDs")
            await self.router.api.led_set(False)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.exception("Unable to disable router LEDs")


class PortForwardSwitch(GliSwitchBase):
    """Representation of a router port forwarding switch."""

    _attr_translation_key = "port_forwarding"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: GLinetSwitchCoordinator, rule_id: str) -> None:
        """Initialize a PortForward switch."""
        super().__init__(coordinator)
        self._rule_id = rule_id
        rule = self.rule
        self._rule_name = rule.name if rule and rule.name else rule_id
        self._attr_translation_placeholders = {"rule_name": self._rule_name}
        self._attr_is_on = rule.enabled if rule else None

    @property
    def rule(self) -> PortForwardRule | None:
        """Return the port forwarding rule from coordinator data or router."""
        if (
            self.coordinator.data is not None
            and self.coordinator.data.port_forward_rules is not None
        ):
            rule = self.coordinator.data.port_forward_rules.get(self._rule_id)
            if isinstance(rule, PortForwardRule):
                return rule
        return self.router.port_forward_rules.get(self._rule_id)

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self.router.factory_mac}/port_forward/{self._rule_id}/"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.rule is not None

    @property
    def is_on(self) -> bool | None:
        """Return if port forwarding rule is enabled."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        if rule := self.rule:
            return rule.enabled
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if rule := self.rule:
            self._attr_is_on = rule.enabled
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, StateType | bool]:
        """Return the switch attributes."""
        rule = self.rule
        if rule is None:
            return {}
        src_port: int | str = rule.src_dport
        if isinstance(src_port, str) and src_port.isdigit():
            src_port = int(src_port)
        dst_port: int | str = rule.dest_port
        if isinstance(dst_port, str) and dst_port.isdigit():
            dst_port = int(dst_port)
        return {
            "protocol": rule.proto,
            "external_port": src_port,
            "internal_ip": rule.dest_ip,
            "internal_port": dst_port,
        }

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the port forwarding rule."""
        rule = self.rule
        if rule is None:
            return
        previous_state = self._attr_is_on
        self._attr_is_on = True
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Enabling port forwarding rule %s", self._rule_id)
            new_rule = PortForwardRule(
                id=rule.id,
                name=rule.name,
                enabled=True,
                src=rule.src,
                dest=rule.dest,
                src_dport=rule.src_dport,
                dest_ip=rule.dest_ip,
                dest_port=rule.dest_port,
                proto=rule.proto,
            )
            await self.router.api.set_port_forward(new_rule)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = previous_state
            self.async_write_ha_state()
            _LOGGER.exception("Unable to enable port forwarding rule %s", self._rule_id)

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the port forwarding rule."""
        rule = self.rule
        if rule is None:
            return
        previous_state = self._attr_is_on
        self._attr_is_on = False
        self.async_write_ha_state()
        try:
            _LOGGER.debug("Disabling port forwarding rule %s", self._rule_id)
            new_rule = PortForwardRule(
                id=rule.id,
                name=rule.name,
                enabled=False,
                src=rule.src,
                dest=rule.dest,
                src_dport=rule.src_dport,
                dest_ip=rule.dest_ip,
                dest_port=rule.dest_port,
                proto=rule.proto,
            )
            await self.router.api.set_port_forward(new_rule)
            await self.coordinator.async_request_refresh()
        except OSError, APIClientError:
            self._attr_is_on = previous_state
            self.async_write_ha_state()
            _LOGGER.exception(
                "Unable to disable port forwarding rule %s", self._rule_id
            )
