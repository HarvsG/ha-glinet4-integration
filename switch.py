"""Support for turning on and off Pi-hole system."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GLINET, DOMAIN
from .router import GLinetRouter, WireGuardClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Pi-hole switch."""
    router: GLinetRouter = hass.data[DOMAIN][entry.entry_id][DATA_GLINET]
    switches: list[WireGuardSwitch | TailscaleSwitch] = []
    if router.wireguard_clients:
        # TODO detect all configured wireguard, openvpn, shadowsocks and
        # TOR clients & servers with router/vpn/status? and gen a switch for each
        switches = [
            WireGuardSwitch(router, client)
            for client in router.wireguard_clients.values()
        ]
    if router.tailscale_configured:
        switches.append(TailscaleSwitch(router))
    if switches:
        async_add_entities(switches, True)


class TailscaleSwitch(SwitchEntity):
    """A tailscale switch."""

    def __init__(self, router: GLinetRouter) -> None:
        """Initialize a GLinet device."""
        self._router = router
        self._attr_device_info = router.device_info

        # self._client = client

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

    @property
    def is_on(self) -> bool:
        """Return if the service is on."""
        return self._router.tailscale_connection

    async def async_turn_on(self) -> None:
        """Turn on the service."""
        try:
            await self._router.api.tailscale_start()
            # TODO since the state takes a while to change we may
            await self._router.update_tailscale_state()
        except OSError:
            _LOGGER.error("Unable to enable tailscale connection")

    async def async_turn_off(self) -> None:
        """Turn off the service."""
        try:
            await self._router.api.tailscale_stop()
            await self._router.update_tailscale_state()
        except OSError:
            _LOGGER.error("Unable to stop tailscale connection")

    @property
    def lan_access(self) -> bool:
        """Whether the router exposes the LAN as a subnet."""
        return self._router.tailscale_config["lan_enabled"]

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enabled by default."""
        return self._router.tailscale_configured

    @property
    def entity_registry_visible_default(self) -> bool:
        """Enabled by default."""
        return self._router.tailscale_configured


class WireGuardSwitch(SwitchEntity):
    """Representation of a VPN switch."""

    # TODO make class, client/server/VPN type agnostic and appreciate >1 can be configured of each
    # And also appreciates that some combinations of states are not permitted by Gl-inet
    # such as can't have a server and a client active of the same VPN type, also can't have
    # multiples of any one type etc etc
    def __init__(self, router: GLinetRouter, client: WireGuardClient) -> None:
        """Initialize a GLinet device."""
        self._router = router
        self._client = client
        self._attr_device_info = router.device_info

    _attr_icon = "mdi:vpn"  # TODO would be better to have MDI style icons for each of the VPN types

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return f"WG Client {self._client.name}"

    @property
    def unique_id(self) -> str:
        """Return the unique id of the switch."""
        return f"glinet_switch/{self._router.factory_mac}/{self._client.name}/wireguard_client"

    @property
    def is_on(self) -> bool:
        """Return if the service is on."""
        # TODO alter property to account for the fact that users can have
        # > 1 client configured, but only one connected
        return self._router.wireguard_connection == self._client

    async def async_turn_on(self) -> None:
        """Turn on the service."""
        try:
            if self._router.connected_wireguard_client not in [self._client, None]:
                await self._router.api.wireguard_client_stop()
                # TODO may need to introduce a delay here, or await confirmation of the stop
            await self._router.api.wireguard_client_start(
                self._client.group_id, self._client.peer_id
            )  # TODO not working
        except OSError:
            _LOGGER.error("Unable to enable WG client")

    async def async_turn_off(self) -> None:
        """Turn off the service."""
        try:
            await self._router.api.wireguard_client_stop()
            # TODO may need to introduce a delay here, or await confirmation of the stop
        except OSError:
            _LOGGER.error("Unable to stop WG client")

    @property
    def entity_category(self) -> EntityCategory:
        """A config entity."""
        return EntityCategory.CONFIG
