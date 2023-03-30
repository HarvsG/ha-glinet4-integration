"""Represent the GLinet router."""
from __future__ import annotations
from dataclasses import dataclass

from datetime import datetime, timedelta
import logging
from typing import Callable

from gli_py import GLinet
from gli_py.error_handling import NonZeroResponse, TokenError

from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DOMAIN as TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD
from homeassistant.core import (  # callback,CALLBACK_TYPE
    HomeAssistant,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.event import async_track_time_interval

# from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, API_PATH

# from typing import Any


# from homeassistant.helpers.event import async_track_time_interval


_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


class GLinetRouter:
    """representation of a GLinet router.
    Should comprise: A method to access the gli_py API
    Basic data and properties about the router
    Configure a home assistant device
    ?TODO make calls to the sensors and device trackers
    that are connected to it
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize a GLinet router.
        Should not be called directly,
        unless then calling async_init()
        """
        # Context info
        self.hass: HomeAssistant = hass
        self._entry: ConfigEntry = entry
        self._options: dict = {}
        self._options.update(entry.options)

        # gli_py API
        self._api: GLinet = None
        self._host: str = entry.data[CONF_HOST]

        # Stable properties
        self._factory_mac: str = "UNKNOWN"
        self._model: str = "UNKNOWN"
        self._sw_v: str = "UNKNOWN"

        # State
        self._devices: dict[str, ClientDevInfo] = {}
        self._connected_devices: int = 0
        self._wireguard_clients: dict[str, WireGuardClient] = {}

        # Flow control
        self._late_init_complete: bool = False
        self._connect_error: bool = False
        self._token_error: bool = False

    async def async_init(self) -> None:
        """Set up a GL-inet router.
        Do some late initialization"""

        try:
            self._api: GLinet = await self.get_api()
        except OSError as exc:
            _LOGGER.error(
                "Error connecting to GL-inet router %s for setup: %s",
                self._host,
                exc,
            )
            raise ConfigEntryNotReady from exc
        try:
            router_info = await self._update_platform(self._api.router_hello)
            self._factory_mac = router_info["mac"]
            self._model = router_info["model"]
            self._sw_v = router_info["version"]
        except Exception as exc: # pylint: disable=broad-except
            # The late initialized variables will remain in
            # their default 'UNKNOWN' state
            _LOGGER.error(
                "Error getting basic device info from GL-inet router %s for setup: %s",
                self._host,
                exc,
            )

        self._late_init_complete = True

    async def setup(self) -> None:
        """Load in old and new entities
        and establish a new session token
        """

        if not self._late_init_complete:
            await self.async_init()

        # On setup we may already have saved tracker entities
        # Load them in and save them to the class
        er_helper = self.hass.helpers.entity_registry
        entity_registry = er_helper.async_get(self.hass)

        track_entries: list[RegistryEntry] = er_helper.async_entries_for_config_entry(
            entity_registry, self._entry.entry_id
        )

        for entry in track_entries:
            if entry.domain == TRACKER_DOMAIN:
                self._devices[entry.unique_id] = ClientDevInfo(
                    entry.unique_id, entry.original_name
                )

        # TODO, should we load in the switch entities

        # Each new setup should renew the token
        await self.renew_token()

        await self.update_all()

        self.add_to_device_registry()

        # TODO here we ask this to update all on the same scan interval
        # but in future some sensors e.g WANip need to update less regularly than
        # others
        async_track_time_interval(self.hass, self.update_all, SCAN_INTERVAL)

    async def get_api(self) -> GLinet:
        """Optimistically returns a GLinet object
        for connection to the API, no test included"""
        conf = self._entry.data
        if CONF_API_TOKEN in conf:
            return GLinet(
                sync=False,
                token=conf[CONF_API_TOKEN],
                base_url=conf[CONF_HOST] + API_PATH,
            )
        if CONF_PASSWORD in conf:
            router = GLinet(sync=False, base_url=conf[CONF_HOST] + API_PATH)
            await router.login(conf[CONF_PASSWORD])
            return router
        else:
            _LOGGER.error(
                "Error setting up GL-inet router, no auth details found in configuration"
            )
            raise ConfigEntryAuthFailed

    async def renew_token(self):
        """Attempt to get a new token."""
        try:
            await self._api.login(self._entry.data[CONF_PASSWORD])

        except Exception as exc:
            _LOGGER.error(
                "GL-inet %s failed to renew the token, have you changed your router password?: %s",
                self._host,
                exc,
            )
            raise ConfigEntryAuthFailed from exc
        new_data = dict(self._entry.data)
        new_data[CONF_API_TOKEN] = self._api.token
        # Update the configuration entry with the new data
        self.hass.config_entries.async_update_entry(self._entry, data=new_data)
        _LOGGER.info(
            "GL-inet router %s token was renewed",
            self._host,
        )

    async def update_all(self, now: datetime | None = None) -> None:
        """Update all Gl-inet platforms."""
        await self.update_device_trackers()
        await self.update_wireguard_client_state()

    async def _update_platform(self, api_callable: Callable):
        """Boilerplate to make update requests to api and handle errors."""

        _LOGGER.debug("Checking client can connect to GL-inet router %s", self._host)
        try:
            if self._token_error:
                await self.renew_token()
            response = await api_callable()
        except TimeoutError as exc:
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.error(
                "GL-inet router %s did not respond in time: %s",
                self._host,
                exc,
            )
            return
        except TokenError as exc:
            self._token_error = True
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.warning(
                "GL-inet router %s token was refused %s, will try to re-autheticate before next poll",
                self._host,
                exc,
            )
            return
        except NonZeroResponse as exc:
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.error(
                "GL-inet router %s responded, but with an error code: %s",
                self._host,
                exc,
            )
            return
        except Exception as exc: # pylint: disable=broad-except
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.error(
                "GL-inet router %s responded with an unexpected error: %s",
                self._host,
                exc,
            )
            return

        if not response:
            _LOGGER.error(
                "Response from %s to request %s is of type %s, Response: %s",
                self._host,
                api_callable.__name__,
                str(type(response)),
                str(response),
            )

        if self._token_error:
            self._token_error = False
            _LOGGER.info("Gl-inet %s token is now renewed", self._host)

        if self._connect_error:
            self._connect_error = False
            _LOGGER.info("Reconnected to Gl-inet router %s", self._host)

        return response

    async def update_device_trackers(self) -> None:
        """Update the device trackers"""

        new_device = False
        wrt_devices = await self._update_platform(self._api.connected_clients)
        consider_home = self._options.get(
            CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
        )
        # track_unknown = self._options.get(CONF_TRACK_UNKNOWN, DEFAULT_TRACK_UNKNOWN)

        # TODO - ensure the output of gli_py devices has the correct data structure
        for device_mac, device in self._devices.items():
            dev_info = wrt_devices.get(device_mac)
            device.update(dev_info, consider_home)

        for device_mac, dev_info in wrt_devices.items():
            if device_mac in self._devices:
                continue
            if not dev_info["name"]:
                continue
            new_device = True
            device = ClientDevInfo(device_mac)
            device.update(dev_info)
            self._devices[device_mac] = device

        async_dispatcher_send(self.hass, self.signal_device_update)
        if new_device:
            async_dispatcher_send(self.hass, self.signal_device_new)

        self._connected_devices = len(wrt_devices)

    async def update_wireguard_client_state(self) -> None:
        """Make call to the API to get the wireguard client state"""
        # TODO as part of changes to switch.py, this probably needs to become
        # client/server/VPN type agnostic it may be that router/vpn/status
        # is a better API endpoint to do it in only 1 call
        response: dict = await self._update_platform(self._api.wireguard_client_list)
        # TODO wireguard_client_list outputs some private info, we don't want it to end up in the logs.
        # May be best to redact it in gli_py.
        for config in response["peers"]:
            self._wireguard_clients[config["name"]] = WireGuardClient(
                name=config["name"], connected=False
            )

        # update wether the currently selected WG client is connected
        response: dict = await self._update_platform(self._api.wireguard_client_state)
        self._wireguard_clients[response["main_server"]].connected = response["enable"]

    def update_options(self, new_options: dict) -> bool:
        """Update router options. Returns True if a reload is required
        Called in __init__.py
        placeholder function because it may become
        neccessary to reload in future.
        """
        req_reload = False
        self._options.update(new_options)
        return req_reload

    def add_to_device_registry(self):
        """Since this router device doesn't always have its
        own entities we need to manually add it to
        the device registry
        """
        device_registry = dr.async_get(self.hass)

        device_registry.async_get_or_create(
            config_entry_id=self._entry.entry_id,
            connections={(CONNECTION_NETWORK_MAC, self.factory_mac)},#TODO In my test local lan uses MAC - 1, 2.4G MAC + 1 and 5G MAC +2
            identifiers={(DOMAIN, self.factory_mac)},
            manufacturer="GL-inet",
            name=self.name,
            model=self.model,
            sw_version=self._sw_v,
        )

    # @property
    # def device_info(self) -> DeviceInfo:
    #     """Return the device information."""
    #     data: DeviceInfo = {
    #       "connections": {(CONNECTION_NETWORK_MAC, self.factory_mac)},
    #       "identifiers": {(DOMAIN, self.factory_mac)},
    #       "name": self.name,
    #       "model": self.model,
    #       "manufacturer": "GL-inet",
    #     }
    #     return data

    @property
    def signal_device_new(self) -> str:
        """Event specific per GL-inet entry to signal new device."""
        return f"{DOMAIN}-device-new"

    @property
    def signal_device_update(self) -> str:
        """Event specific per GL-inet entry to signal updates in devices."""
        return f"{DOMAIN}-device-update"

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

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
        """Return router model"""
        return self._model.upper()

    @property
    def name(self) -> str:
        """Return router name."""
        # TODO retrieve the friendly name of the router e.g MT1300 is Beryl
        return f"GL-inet {self._model.upper()}"

    @property
    def wireguard_clients(self) -> dict[str, WireGuardClient]:
        """Return router factory_mac."""
        return self._wireguard_clients

    @property
    def connected_wireguard_client(self) -> None | WireGuardClient:
        """Return the wirguard client that is connected, if any."""
        for client in self._wireguard_clients.values():
            if client.connected:
                return client
        return None


@dataclass
class WireGuardClient:
    """Class for keeping track of WireGuard Client Configs."""

    name: str
    connected: bool


class ClientDevInfo:
    """Representation of a device connected to the router."""

    def __init__(self, mac: str, name=None) -> None:
        """Initialize a connected device."""
        self._mac: str = mac
        self._name: str | None = name
        self._ip_address: str | None = None
        self._last_activity: datetime = dt_util.utcnow() - timedelta(days=1)
        self._connected: bool = False

    def update(self, dev_info: dict = None, consider_home=0):
        """Update connected device info."""
        now: datetime = dt_util.utcnow()
        if dev_info:
            if not self._name:
                # GLinet router name unknown devices "*"
                if dev_info["name"] == "*" or dev_info["name"] == "":
                    self._name = self._mac.replace(":", "_")
                else:
                    self._name = dev_info["name"]
            self._ip_address = dev_info["ip"]
            self._last_activity = now
            self._connected = dev_info["online"]

        # a device might not actually be online but we want to consider it home
        elif self._connected:
            self._connected = (
                now - self._last_activity
            ).total_seconds() < consider_home
            self._ip_address = None

    @property
    def is_connected(self):
        """Return connected status."""
        return self._connected

    @property
    def mac(self):
        """Return device mac address."""
        return self._mac

    @property
    def name(self):
        """Return device name."""
        return self._name

    @property
    def ip_address(self):
        """Return device ip address."""
        return self._ip_address

    @property
    def last_activity(self):
        """Return device last activity."""
        return self._last_activity
