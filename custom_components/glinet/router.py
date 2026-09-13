"""Represent the GLinet router."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, TypeVar

from gli4py import GLinet
from gli4py.enums import TailscaleConnection
from gli4py.error_handling import AuthenticationError, NonZeroResponse, TokenError
from uplink import AiohttpClient

from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DOMAIN as TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import API_PATH, DOMAIN
from .utils import adjust_mac

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
T = TypeVar("T")

# PEP 695 type aliases are evaluated lazily, so the forward
# reference to GLinetRouter is resolved when first used
type GLinetConfigEntry = ConfigEntry[GLinetRouter]  # pylint: disable=used-before-assignment


class DeviceInterfaceType(StrEnum):
    """Enum for the possible interface types reported by glipy."""

    WIFI_24 = "2.4GHz"
    WIFI_5 = "5GHz"
    LAN = "LAN"
    WIFI_24_GUEST = "2.4GHz Guest"
    WIFI_5_GUEST = "5GHz Guest"
    UNKNOWN = "Unknown"
    DONGLE = "Dongle"
    BYPASS_ROUTE = "Bypass Route"
    MLO = "MLO"
    MLO_GUEST = "MLO Guest"
    WIFI_6 = "6GHz"
    WIFI_6_GUEST = "6GHz Guest"


# Maps the integer interface type reported by the API to a member of
# DeviceInterfaceType. The API uses two distinct indices for "unknown".
DEVICE_INTERFACE_TYPE_MAP: dict[int, DeviceInterfaceType] = {
    0: DeviceInterfaceType.WIFI_24,
    1: DeviceInterfaceType.WIFI_5,
    2: DeviceInterfaceType.LAN,
    3: DeviceInterfaceType.WIFI_24_GUEST,
    4: DeviceInterfaceType.WIFI_5_GUEST,
    5: DeviceInterfaceType.UNKNOWN,
    6: DeviceInterfaceType.DONGLE,
    7: DeviceInterfaceType.BYPASS_ROUTE,
    8: DeviceInterfaceType.UNKNOWN,
    9: DeviceInterfaceType.MLO,
    10: DeviceInterfaceType.MLO_GUEST,
    11: DeviceInterfaceType.WIFI_6,
    12: DeviceInterfaceType.WIFI_6_GUEST,
}


class GLinetRouter:
    """representation of a GLinet router.

    Should comprise: A method to access the gli4py API
    Basic data and properties about the router
    Configure a home assistant device
    ?TODO make calls to the sensors and device trackers
    that are connected to it.
    """

    def __init__(self, hass: HomeAssistant, entry: GLinetConfigEntry) -> None:
        """Initialize a GLinet router.

        Should not be called directly,
        unless then calling async_init().
        """
        # Context info
        self.hass: HomeAssistant = hass
        self._entry: GLinetConfigEntry = entry
        # Options take precedence, but fall back to entry data for entries
        # created before consider_home moved to options
        self._consider_home: float = entry.options.get(
            CONF_CONSIDER_HOME,
            entry.data.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()),
        )

        # gli4py API
        self._api: GLinet
        self._host: str = entry.data[CONF_HOST]

        # Stable properties
        self._factory_mac: str = "UNKNOWN"
        self._model: str = "UNKNOWN"
        self._sw_v: str = "UNKNOWN"

        # State
        self._devices: dict[str, ClientDevInfo] = {}
        self._connected_devices: int = 0
        self._wifi_ifaces: dict[str, WifiInterface] = {}
        self._system_status: dict = {}
        self._wireguard_clients: dict[str, WireGuardClient] = {}
        self._wireguard_connections: list[WireGuardClient] | None = None
        self._tailscale_config: dict = {}
        self._tailscale_connection: bool | None = None

        # Flow control
        self._late_init_complete: bool = False
        self._connect_error: bool = False
        self._token_error: bool = False
        self._unsub_update: CALLBACK_TYPE | None = None

    async def async_init(self) -> None:
        """Set up a GL-iNet router.

        Do some late initialization
        """

        self._api = self._create_api()
        try:
            await self.renew_token()
        except ConfigEntryAuthFailed:
            raise
        except Exception as exc:
            _LOGGER.exception(
                "Error connecting to GL-iNet router %s",
                self._host,
            )
            raise ConfigEntryNotReady from exc
        try:
            router_info = await self._update_platform(self._api.router_info)
            assert router_info is not None
        except Exception as exc:  # pylint: disable=broad-except
            # The late initialized variables will remain in
            # their default 'UNKNOWN' state
            _LOGGER.exception(
                "Error getting basic device info from GL-iNet router %s",
                self._host,
            )
            raise ConfigEntryNotReady from exc

        _LOGGER.debug("Router info retrieved: %s", router_info)
        self._model = router_info[CONF_MODEL]
        self._sw_v = router_info["firmware_version"]
        self._factory_mac = router_info[CONF_MAC]

        self._late_init_complete = True

    async def setup(self) -> None:
        """Load in old and new entities and establish a new session token."""

        if not self._late_init_complete:
            await self.async_init()

        # On setup we may already have saved tracker entities
        # Load them in and save them to the class
        entity_registry = er.async_get(self.hass)

        track_entries: list[RegistryEntry] = er.async_entries_for_config_entry(
            entity_registry, self._entry.entry_id
        )

        for entry in track_entries:
            if entry.domain == TRACKER_DOMAIN:
                self._devices[entry.unique_id] = ClientDevInfo(
                    entry.unique_id, entry.original_name
                )

        # Update device tracker and switch entities
        await self.update_all()

        # TODO here we ask this to update all on the same scan interval
        # but in future some sensors e.g WANip need to update less regularly than
        # others
        self._unsub_update = async_track_time_interval(
            self.hass, self.update_states, SCAN_INTERVAL
        )

    @callback
    def unload(self) -> None:
        """Cancel the periodic update timer."""
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

    def _create_api(self) -> GLinet:
        """Optimistically return a GLinet object for connection to the API, no test included."""
        conf = self._entry.data
        shared_session = async_get_clientsession(self.hass)
        ha_client = AiohttpClient(session=shared_session)

        if CONF_PASSWORD in conf:
            return GLinet(
                sync=False, base_url=conf[CONF_HOST] + API_PATH, client=ha_client
            )
        _LOGGER.error(
            "Error setting up GL-iNet router, no auth details found in configuration"
        )
        raise ConfigEntryAuthFailed

    async def renew_token(self) -> None:
        """Attempt to get a new token."""
        try:
            await self._api.login(
                self._entry.data[CONF_USERNAME], self._entry.data[CONF_PASSWORD]
            )
            _LOGGER.info(
                "GL-iNet router %s token was renewed",
                self._host,
            )
        except (AuthenticationError, TokenError) as exc:
            _LOGGER.exception(
                "GL-iNet %s failed to renew the token, have you changed your router password?",
                self._host,
            )
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            _LOGGER.warning(
                "Could not connect to GL-iNet router to renew token: %s", exc
            )
            raise  # Let generic network/timeout exceptions bubble up normally

    async def update_all(self, _: datetime | None = None) -> None:
        """Update all Gl-inet platforms."""
        await self.update_system_status()
        await self.update_device_trackers()
        await self.update_wifi_ifaces_state()
        await self.update_wireguard_client_state()
        await self.update_tailscale_state()

    async def update_states(self, _: datetime | None = None) -> None:
        """Update platforms and states that aren't handled elsewhere."""
        try:
            await self.update_system_status()
            await self.update_device_trackers()
            # If a user may have many switches, best to update in bulk
            await self.update_wifi_ifaces_state()
            await self.update_wireguard_client_state()
        except ConfigEntryAuthFailed:
            # ConfigEntryAuthFailed is only handled by HA when raised from
            # entry setup or entity updates, not from a timer callback
            self._entry.async_start_reauth(self.hass)

    async def _update_platform(
        self, api_callable: Callable[[], Coroutine[Any, Any, T]]
    ) -> T | None:
        """Boilerplate to make update requests to api and handle errors."""

        try:
            if self._token_error:
                _LOGGER.debug(
                    "The last requested resulted in a token error - so renewing token"
                )
                await self.renew_token()
            if self._connect_error:
                _LOGGER.debug("Got pending connect error - attempting to renew token")
                await self.renew_token()
            _LOGGER.debug(
                "Making api call %s from _update_platform()", api_callable.__name__
            )
            response = await api_callable()
        except TimeoutError:
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL-iNet router %s did not respond in time",
                    self._host,
                )
            return None
        except TokenError as exc:
            self._token_error = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.warning(
                    "GL-iNet router %s token was refused %s, will try to re-autheticate before next poll",
                    self._host,
                    exc,
                )
            return None
        except NonZeroResponse:
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL-iNet router %s responded, but with an error code", self._host
                )
            return None
        except ConfigEntryAuthFailed:
            # Bubble up to Home Assistant to pause polling and trigger the re-auth flow
            raise
        except Exception:  # pylint: disable=broad-except  # noqa: BLE001
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.exception(
                "GL-iNet router %s responded with an unexpected error", self._host
            )
            return None

        if not response:
            _LOGGER.debug(
                "Invalid response from %s to request %s is of type %s, Response: %s",
                self._host,
                api_callable.__name__,
                str(type(response)),
                str(response),
            )

        if self._token_error:
            self._token_error = False
            _LOGGER.info(
                "Gl-inet %s new token has successfully made an API call, token marked as valid",
                self._host,
            )

        if self._connect_error:
            self._connect_error = False
            _LOGGER.info("Reconnected to Gl-inet router %s", self._host)
        _LOGGER.debug(
            "_update_platform() completed without error for callable %s, returning response: %s",
            api_callable.__name__,
            str(response)[:200],
        )
        return response

    async def update_system_status(self) -> None:
        """Update the system status from the API."""

        status = await self._update_platform(self._api.router_get_status)
        # For now only the content of the `system` field seems of use
        if status:
            self._system_status = status.get("system", {})

    async def update_device_trackers(self) -> None:
        """Update the device trackers."""

        new_device = False
        wrt_devices = await self._update_platform(self._api.connected_clients)
        if not wrt_devices:
            _LOGGER.warning(
                "Router returned no valid connected devices. It returned %s of type %s",
                str(wrt_devices),
                type(wrt_devices),
            )
            if wrt_devices is None or wrt_devices == {}:
                self._connected_devices = 0
            return
        # TODO - ensure the output of gli4py devices has the correct data structure
        for device_mac, device in self._devices.items():
            dev_info = wrt_devices.get(device_mac)
            device.update(dev_info, self._consider_home)

        for device_mac, dev_info in wrt_devices.items():
            # Skip if we've already have this device
            if device_mac in self._devices:
                continue

            alias = dev_info.get("alias", "").strip()
            name = dev_info.get("name", "").strip()
            # Skip if both alias and name are empty
            if not alias and not name:
                continue

            new_device = True
            device = ClientDevInfo(device_mac)
            device.update(dev_info)
            self._devices[device_mac] = device

        async_dispatcher_send(self.hass, self.signal_device_update)
        if new_device:
            async_dispatcher_send(self.hass, self.signal_device_new)

        self._connected_devices = len(wrt_devices)

    async def update_wifi_ifaces_state(self) -> None:
        """Make a call to the API to get the WiFi ifaces config state."""
        ifaces = await self._update_platform(self._api.wifi_ifaces_get)
        if not ifaces:
            return
        for name, iface in ifaces.items():
            self._wifi_ifaces[name] = WifiInterface(
                name=name,
                enabled=iface.get("enabled", False),
                ssid=iface.get("ssid", ""),
                guest=iface.get("guest", False),
                hidden=iface.get("hidden", False),
                encryption=iface.get("encryption", "UNKNOWN"),
            )

    async def update_tailscale_state(self) -> None:
        """Make a call to the API to get the tailscale state."""

        configured = await self._update_platform(self._api.tailscale_configured)
        if configured is None:
            # The request failed - keep the previous state
            return
        if not configured:
            self._tailscale_config = {}
            return
        # TODO this is a placeholder that needs to be replaced with a pulic method that combines useful info in _tailscale_status and _tailscale_get_config
        self._tailscale_config = (
            await self._update_platform(
                self._api._tailscale_get_config  # pylint: disable=protected-access  # noqa: SLF001
            )
            or {}
        )
        state: TailscaleConnection | None = await self._update_platform(
            self._api.tailscale_connection_state
        )
        if state is None:
            # The request failed - keep the previous state
            return
        self._tailscale_connection = state == TailscaleConnection.CONNECTED

    async def update_wireguard_client_state(self) -> None:
        """Make call to the API to get the wireguard client state."""
        # TODO as part of changes to switch.py, this probably needs to become
        # client/server/VPN type agnostic it may be that router/vpn/status
        # is a better API endpoint to do it in only 1 call
        response = await self._update_platform(self._api.wireguard_client_list)
        if not response:
            return
        for config in response:
            name = config.get("name")
            peer_id = config.get("peer_id")
            group_id = config.get("group_id")
            if name is None or peer_id is None or group_id is None:
                # Don't log the config values, they contain private key material
                _LOGGER.debug(
                    "Skipping malformed WireGuard client config with keys: %s",
                    sorted(config),
                )
                continue
            self._wireguard_clients[peer_id] = WireGuardClient(
                name=name,
                connected=False,
                group_id=group_id,
                peer_id=peer_id,
                tunnel_id=config.get("tunnel_id"),
            )

        if len(self._wireguard_clients) == 0:
            _LOGGER.debug("No wireguard clients, there is nothing to update")
            return

        # update whether the currently selected WG client is connected
        response = await self._update_platform(self._api.wireguard_client_state)
        if not response:
            return
        # 0 is disconnted, 1 is connected, 2 is connecting
        self._wireguard_connections = []
        for config in response:
            # OpenVPN configs are sometimes returned leading to errors.
            if config.get("type") != "wireguard":
                continue
            # if config["enabled"] is false then status does not exist
            connected: bool = config.get("status", 0) != 0

            client = self._wireguard_clients.get(config.get("peer_id"))
            if client is None:
                continue
            client.tunnel_id = config.get("tunnel_id")
            client.connected = connected
            if connected:
                # If more modern firmware supports more than 1 client being connected, we need to change this
                self._wireguard_connections.append(client)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""

        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.unique_id or self.factory_mac)},
            connections={
                (CONNECTION_NETWORK_MAC, format_mac(self.factory_mac)),
                (CONNECTION_NETWORK_MAC, adjust_mac(self.factory_mac, 1)),
            },
            name=self.name,
            model=self.model or "GL-iNet Router",
            manufacturer="GL-iNet",
            configuration_url=self._host,
            sw_version=self._sw_v,
        )

    @property
    def signal_device_new(self) -> str:
        """Event specific per GL-iNet entry to signal new device."""
        return f"{DOMAIN}-device-new-{self._factory_mac}"

    @property
    def signal_device_update(self) -> str:
        """Event specific per GL-iNet entry to signal updates in devices."""
        return f"{DOMAIN}-device-update-{self._factory_mac}"

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

    @property
    def unique_id(self) -> str:
        """Return router unique id."""
        return self._entry.unique_id or self._entry.entry_id

    @property
    def devices(self) -> dict[str, ClientDevInfo]:
        """Return devices."""
        return self._devices

    @property
    def api(self) -> GLinet:
        """Return router API."""
        return self._api

    @property
    def factory_mac(self) -> str:
        """Return router factory_mac."""
        return self._factory_mac

    @property
    def model(self) -> str:
        """Return router model."""
        return self._model.upper()

    @property
    def sw_version(self) -> str:
        """Return router firmware version."""
        return self._sw_v

    @property
    def available(self) -> bool:
        """Return True when the last poll of the router succeeded."""
        return not self._connect_error

    @property
    def connected_devices_count(self) -> int:
        """Return the number of currently connected client devices."""
        return self._connected_devices

    @property
    def name(self) -> str:
        """Return router name."""
        # TODO retrieve the friendly name of the router e.g MT1300 is Beryl
        return f"GL-iNet {self._model.upper()}"

    @property
    def wifi_ifaces(self) -> dict[str, WifiInterface]:
        """Return router wifi interfaces."""
        return self._wifi_ifaces

    @property
    def wireguard_clients(self) -> dict[str, WireGuardClient]:
        """Return router factory_mac."""
        return self._wireguard_clients

    @property
    def connected_wireguard_clients(self) -> None | list[WireGuardClient]:
        """Return the wireguard clients that are connected, if any."""
        return self._wireguard_connections

    @property
    def tailscale_configured(self) -> bool:
        """Is tailscale configured."""
        return self._tailscale_config != {}

    @property
    def tailscale_connection(self) -> bool | None:
        """Property for tailscale connection."""
        if not self.tailscale_configured:
            return None
        return self._tailscale_connection

    @property
    def tailscale_config(self) -> dict:
        """Property for tailscale connection."""
        # TODO, we need a non private API method that returns some useful config info
        return self._tailscale_config

    @property
    def system_status(self) -> dict:
        """Property for system status."""

        return self._system_status


@dataclass
class WireGuardClient:
    """Class for keeping track of WireGuard Client Configs."""

    name: str
    connected: bool = field(compare=False)
    group_id: int
    peer_id: int
    tunnel_id: int | None


@dataclass
class WifiInterface:
    """Class for keeping track of Wifi Interfaces."""

    name: str
    enabled: bool
    ssid: str
    guest: bool
    hidden: bool
    encryption: str


class ClientDevInfo:
    """Representation of a device connected to the router."""

    def __init__(self, mac: str, name: str | None = None) -> None:
        """Initialize a connected device."""
        self._mac: str = mac
        self._name: str | None = name
        self._ip_address: str | None = None
        self._last_activity: datetime = dt_util.utcnow() - timedelta(days=1)
        self._connected: bool = False
        self._if_type: DeviceInterfaceType = DeviceInterfaceType.UNKNOWN

    def update(self, dev_info: dict | None = None, consider_home: float = 0) -> None:
        """Update connected device info."""
        now: datetime = dt_util.utcnow()
        if dev_info:
            # Prefer the user-defined alias as a name
            alias = dev_info.get("alias")
            if alias and alias.strip():
                self._name = alias
            else:
                # If no alias, fallback to auto-assigned name field
                name = dev_info.get("name", "")
                if name == "*" or not name.strip():
                    self._name = self._mac.replace(":", "_")
                else:
                    self._name = name
            self._ip_address = dev_info.get("ip")
            self._last_activity = now
            self._connected = dev_info.get("online", False)
            self._if_type = DEVICE_INTERFACE_TYPE_MAP.get(
                dev_info.get("type", 5), DeviceInterfaceType.UNKNOWN
            )
        # a device might not actually be online but we want to consider it home
        elif self._connected:
            self._connected = (
                now - self._last_activity
            ).total_seconds() < consider_home
            self._ip_address = None

    @property
    def is_connected(self) -> bool:
        """Return connected status."""
        return self._connected

    @property
    def interface_type(self) -> DeviceInterfaceType:
        """Return device interface type."""
        return self._if_type

    @property
    def mac(self) -> str:
        """Return device mac address."""
        return self._mac

    @property
    def name(self) -> str | None:
        """Return device name."""
        return self._name

    @property
    def ip_address(self) -> str | None:
        """Return device ip address."""
        return self._ip_address

    @property
    def last_activity(self) -> datetime:
        """Return device last activity."""
        return self._last_activity
