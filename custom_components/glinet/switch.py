"""Support for turning on and off Pi-hole system."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .const import DATA_GLINET, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .router import GLinetRouter, WifiInterface, WireGuardClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Pi-hole switch."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    switches: list[WifiApSwitch | WireGuardSwitch | TailscaleSwitch] = []
    if router.wireguard_clients:
        # TODO detect all configured wireguard, openvpn, shadowsocks and
        # TOR clients & servers with router/vpn/status? and gen a switch for each
        switches = [
            WireGuardSwitch(router, client)
            for client in router.wireguard_clients.values()
        ]
    if router.tailscale_configured:
        switches.append(TailscaleSwitch(router))
    for iface_name, iface in router.wifi_ifaces.items():
        switches.append(WifiApSwitch(router, iface_name, iface))
    if switches:
        async_add_entities(switches, True)


class GliSwitchBase(SwitchEntity):
    """GL-inet switch base class."""

    def __init__(self, router: GLinetRouter) -> None:
        """Initialize a GLinet device."""
        self._router = router
        self._attr_device_info = router.device_info

    _attr_has_entity_name = True

    @property
    def is_on(self) -> bool | None:
        """Return if the service is on."""
        return self._attr_is_on

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG


class WifiApSwitch(GliSwitchBase):
    """A WiFi AccessPoint switch."""

    def __init__(
        self, router: GLinetRouter, iface_name: str, iface: WifiInterface
    ) -> None:
        """Initialize a GLinet device."""
        super().__init__(router)
        self._iface_name = iface_name
        self._iface = iface

    @property
    def icon(self) -> str:
        """Return AP state icon."""
        if self.is_on:
            return "mdi:wifi"
        return "mdi:wifi-off"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._iface.ssid if self._iface.ssid else self._iface.name

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self._router.factory_mac}/iface_{self._iface_name}"

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        """Return the attributes."""
        attrs: dict[str, str | bool] = {}
        attrs["interface"] = self._iface.name
        attrs["guest"] = self._iface.guest
        attrs["ssid"] = self._iface.ssid
        attrs["hidden"] = self._iface.hidden
        attrs["encryption"] = self._iface.encryption
        return attrs

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the AP."""
        try:
            _LOGGER.debug("Enabling WiFi interface %s", self._iface_name)
            await self._router.api.wifi_iface_set_enabled(self._iface_name, True)
        except OSError:
            _LOGGER.exception(
                "Unable to enable WiFi interface %s",
                self._iface_name,
            )
        else:
            # be optimistic
            self._attr_is_on = True
            self.async_write_ha_state()

            # fetch the state #TODO try block?
            await self._router.update_wifi_ifaces_state()
            await self.async_update()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the AP."""
        try:
            _LOGGER.debug("Disabling WiFi interface %s", self._iface_name)
            await self._router.api.wifi_iface_set_enabled(self._iface_name, False)
        except OSError:
            _LOGGER.exception(
                "Unable to disable WiFi interface %s",
                self._iface_name,
            )
        else:
            # be optimistic
            self._attr_is_on = False
            self.async_write_ha_state()

            # fetch the state #TODO try block?
            await self._router.update_wifi_ifaces_state()
            await self.async_update()

    @callback
    async def async_update(self) -> None:
        """Update the switch state."""
        _LOGGER.debug(
            "Updating WiFi AP switch with stored state for %s",
            self._iface_name,
        )
        self._iface = self._router.wifi_ifaces.get(self._iface_name) or self._iface
        self._attr_is_on = self._iface.enabled


class TailscaleSwitch(GliSwitchBase):
    """A tailscale switch."""

    _attr_icon = "mdi:vpn"  # TODO would be better to have MDI style icons for each of the VPN types

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        # TODO we could add the login_name here, but we lose access to that value when the connection drops
        return "Tailscale"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self._router.factory_mac}/tailscale"

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        try:
            _LOGGER.debug("Enabling tailscale")
            await self._router.api.tailscale_start()
            # TODO since the state takes a while to change we may
        except OSError:
            _LOGGER.exception("Unable to enable tailscale connection")
        else:
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        try:
            _LOGGER.debug("Enabling tailscale")
            await self._router.api.tailscale_stop()
        except OSError:
            _LOGGER.exception("Unable to stop tailscale connection")
        else:
            self._attr_is_on = False
            self.async_write_ha_state()

    @property
    def lan_access(self) -> bool | None:
        """Whether the router exposes the LAN as a subnet."""
        la = self._router.tailscale_config.get("lan_enabled")
        if la is not None:
            return bool(la)
        return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enabled by default."""
        return self._router.tailscale_configured

    @property
    def entity_registry_visible_default(self) -> bool:
        """Enabled by default."""
        return self._router.tailscale_configured

    @callback
    async def async_update(self) -> None:
        """Update the switch state. Only one tailscale connection can be configured so this is not expensive."""
        _LOGGER.debug("Updating Tailscale switch state")
        await self._router.update_tailscale_state()
        self._attr_is_on = self._router.tailscale_connection


class WireGuardSwitch(GliSwitchBase):
    """Representation of a VPN switch."""

    # TODO make class, client/server/VPN type agnostic and appreciate >1 can be configured of each
    # And also appreciates that some combinations of states are not permitted by Gl-inet
    # such as can't have a server and a client active of the same VPN type, also can't have
    # multiples of any one type etc etc
    def __init__(self, router: GLinetRouter, client: WireGuardClient) -> None:
        """Initialize a GLinet device."""
        super().__init__(router)
        self._client = client
        self._attr_device_info = router.device_info
        self._attr_is_on: bool = False

    _attr_icon = "mdi:vpn"  # TODO would be better to have MDI style icons for each of the VPN types

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"WG Client {self._client.name}"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self._router.factory_mac}/{self._client.name}/wireguard_client"

    async def async_turn_on(self, **_: Any) -> None:
        """Turn on the service."""
        try:
            # TODO Verify that the API doesn't do this for us
            if (
                self._client.tunnel_id
                is None  # This confirms we are using older firmware
                and self._router.connected_wireguard_clients is not None
                and self._client not in self._router.connected_wireguard_clients
            ):
                for client in self._router.connected_wireguard_clients:
                    await self._router.api.wireguard_client_stop(client.peer_id)
                # TODO may need to introduce a delay here, or await confirmation of the stop

            await self._router.api.wireguard_client_start(
                self._client.group_id, self._client.tunnel_id or self._client.peer_id
            )
        except OSError:
            _LOGGER.exception("Unable to enable WG client")
        else:
            self._attr_is_on = True
            self.async_write_ha_state()
            await self._router.update_wireguard_client_state()
            await self.async_update()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn off the service."""
        try:
            await self._router.api.wireguard_client_stop(
                self._client.tunnel_id or self._client.peer_id
            )
            # TODO may need to introduce a delay here, or await confirmation of the stop
        except OSError:
            _LOGGER.exception("Unable to stop WG client")
        else:
            # be optimistic
            self._attr_is_on = False
            self.async_write_ha_state()
            await self._router.update_wireguard_client_state()
            await self.async_update()

    @callback
    async def async_update(self) -> None:
        """Update the switch state. A user may have many so don't call the API for each."""
        _LOGGER.debug("Updating WG client switch state from stored info")
        self._attr_is_on = self._client in (self._router.wireguard_connections or [])
