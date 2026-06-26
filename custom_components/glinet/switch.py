"""Switch platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetUpdateCoordinator
    from .models import WifiInterface, WireGuardClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the GL-iNet switches."""
    coordinator = entry.runtime_data
    data = coordinator.data
    switches: list[WifiApSwitch | WireGuardSwitch | TailscaleSwitch] = []
    if data.wireguard_clients:
        # TODO detect all configured wireguard, openvpn, shadowsocks and
        # TOR clients & servers with router/vpn/status? and gen a switch for each
        switches = [
            WireGuardSwitch(coordinator, client)
            for client in data.wireguard_clients.values()
        ]
    if data.tailscale_config:
        switches.append(TailscaleSwitch(coordinator))
    for iface_name, iface in data.wifi_ifaces.items():
        switches.append(WifiApSwitch(coordinator, iface_name, iface))
    if switches:
        async_add_entities(switches)


class GliSwitchBase(CoordinatorEntity["GLinetUpdateCoordinator"], SwitchEntity):
    """GL-inet switch base class."""

    # Bind the concrete coordinator type so `self.coordinator.data` is typed as
    # GLinetData rather than Any (the generic parameter isn't propagated to the
    # attribute by the homeassistant stubs).
    coordinator: GLinetUpdateCoordinator

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize a GLinet switch."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info


class WifiApSwitch(GliSwitchBase):
    """A WiFi AccessPoint switch."""

    def __init__(
        self,
        coordinator: GLinetUpdateCoordinator,
        iface_name: str,
        iface: WifiInterface,
    ) -> None:
        """Initialize a GLinet device."""
        super().__init__(coordinator)
        self._iface_name = iface_name
        self._iface_fallback = iface
        self._attr_unique_id = (
            f"glinet_switch/{coordinator.factory_mac}/iface_{iface_name}"
        )

    @property
    def _iface(self) -> WifiInterface:
        """Return the current interface state from the coordinator."""
        return (
            self.coordinator.data.wifi_ifaces.get(self._iface_name)
            or self._iface_fallback
        )

    @property
    def is_on(self) -> bool:
        """Return if the AP is enabled."""
        return self._iface.enabled

    @property
    def icon(self) -> str:
        """Return AP state icon."""
        if self.is_on:
            return "mdi:wifi"
        return "mdi:wifi-off"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._iface.ssid or self._iface.name

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        """Return the attributes."""
        iface = self._iface
        return {
            "interface": iface.name,
            "guest": iface.guest,
            "ssid": iface.ssid,
            "hidden": iface.hidden,
            "encryption": iface.encryption,
        }

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the AP."""
        try:
            _LOGGER.debug("Enabling WiFi interface %s", self._iface_name)
            await self.coordinator.api.wifi_iface_set_enabled(self._iface_name, True)
        except OSError:
            _LOGGER.exception("Unable to enable WiFi interface %s", self._iface_name)
        else:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the AP."""
        try:
            _LOGGER.debug("Disabling WiFi interface %s", self._iface_name)
            await self.coordinator.api.wifi_iface_set_enabled(self._iface_name, False)
        except OSError:
            _LOGGER.exception("Unable to disable WiFi interface %s", self._iface_name)
        else:
            await self.coordinator.async_request_refresh()


class TailscaleSwitch(GliSwitchBase):
    """A tailscale switch."""

    _attr_icon = "mdi:vpn"
    _attr_name = "Tailscale"

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize the Tailscale switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"glinet_switch/{coordinator.factory_mac}/tailscale"

    @property
    def is_on(self) -> bool | None:
        """Return if tailscale is connected."""
        return self.coordinator.data.tailscale_connection

    @property
    def lan_access(self) -> bool | None:
        """Whether the router exposes the LAN as a subnet."""
        la = self.coordinator.data.tailscale_config.get("lan_enabled")
        if la is not None:
            return bool(la)
        return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enabled by default."""
        return bool(self.coordinator.data.tailscale_config)

    @property
    def entity_registry_visible_default(self) -> bool:
        """Visible by default."""
        return bool(self.coordinator.data.tailscale_config)

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        try:
            _LOGGER.debug("Enabling tailscale")
            await self.coordinator.api.tailscale_start()
        except OSError:
            _LOGGER.exception("Unable to enable tailscale connection")
        else:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        try:
            _LOGGER.debug("Disabling tailscale")
            await self.coordinator.api.tailscale_stop()
        except OSError:
            _LOGGER.exception("Unable to stop tailscale connection")
        else:
            await self.coordinator.async_request_refresh()


class WireGuardSwitch(GliSwitchBase):
    """Representation of a VPN switch."""

    _attr_icon = "mdi:vpn"

    # TODO make class, client/server/VPN type agnostic and appreciate >1 can be configured of each
    def __init__(
        self, coordinator: GLinetUpdateCoordinator, client: WireGuardClient
    ) -> None:
        """Initialize a GLinet device."""
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = (
            f"glinet_switch/{coordinator.factory_mac}/{client.name}/wireguard_client"
        )

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"WG Client {self._client.name}"

    @property
    def _current(self) -> WireGuardClient:
        """Return the current client state from the coordinator (by peer_id)."""
        return self.coordinator.data.wireguard_clients.get(
            self._client.peer_id, self._client
        )

    @property
    def is_on(self) -> bool:
        """Return whether this WireGuard client is connected."""
        return self._current.connected

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        data = self.coordinator.data
        current = self._current
        try:
            # On older firmware only one client may be connected at a time, so
            # stop any other active client first.
            if (
                current.tunnel_id is None
                and data.wireguard_connections
                and not any(
                    c.peer_id == current.peer_id for c in data.wireguard_connections
                )
            ):
                for client in data.wireguard_connections:
                    await self.coordinator.api.wireguard_client_stop(client.peer_id)

            await self.coordinator.api.wireguard_client_start(
                current.group_id, current.tunnel_id or current.peer_id
            )
        except OSError:
            _LOGGER.exception("Unable to enable WG client")
        else:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        current = self._current
        try:
            await self.coordinator.api.wireguard_client_stop(
                current.tunnel_id or current.peer_id
            )
        except OSError:
            _LOGGER.exception("Unable to stop WG client")
        else:
            await self.coordinator.async_request_refresh()
