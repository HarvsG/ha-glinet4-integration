"""DataUpdateCoordinator for the GL-iNet integration."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_PATH, DOMAIN, SCAN_INTERVAL
from .models import ClientDevInfo, WifiInterface, WireGuardClient
from .utils import adjust_mac

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class GLinetData:
    """Snapshot of router state exposed to entities each refresh.

    Holds references to the coordinator's working collections (not copies);
    entities read it fresh after every coordinator update.
    """

    system_status: dict = field(default_factory=dict)
    devices: dict[str, ClientDevInfo] = field(default_factory=dict)
    connected_devices: int = 0
    wifi_ifaces: dict[str, WifiInterface] = field(default_factory=dict)
    wireguard_clients: dict[int, WireGuardClient] = field(default_factory=dict)
    wireguard_connections: list[WireGuardClient] = field(default_factory=list)
    tailscale_config: dict = field(default_factory=dict)
    tailscale_connection: bool | None = None


class GLinetUpdateCoordinator(DataUpdateCoordinator[GLinetData]):
    """Coordinate polling of a GL-iNet router and own its API client.

    Replaces the old ``GLinetRouter``: it holds the device identity and the
    gli4py client, and produces a ``GLinetData`` snapshot every ``SCAN_INTERVAL``
    which all entities consume via ``CoordinatorEntity``.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # always_update stays True (default): trackers mutate state in place, so
        # always_update=False would compare snapshots equal and drop their updates.
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self._options: dict = dict(entry.options)

        self._api: GLinet
        self._host: str = entry.data[CONF_HOST]

        self._factory_mac: str = "UNKNOWN"
        self._model: str = "UNKNOWN"
        self._sw_v: str = "UNKNOWN"

        self._devices: dict[str, ClientDevInfo] = {}
        self._connected_devices: int = 0
        self._wifi_ifaces: dict[str, WifiInterface] = {}
        self._system_status: dict = {}
        self._wireguard_clients: dict[int, WireGuardClient] = {}
        self._wireguard_connections: list[WireGuardClient] = []
        self._tailscale_config: dict = {}
        self._tailscale_connection: bool | None = None

        self._late_init_complete: bool = False
        self._connect_error: bool = False
        self._token_error: bool = False
        # Set by _update_platform when any call hits a transport error this
        # cycle, so _async_update_data can fail the whole refresh
        self._cycle_failed: bool = False

    async def async_setup(self) -> None:
        """Authenticate, load identity and restore known trackers.

        Called once from ``async_setup_entry`` before the first refresh.
        """
        if not self._late_init_complete:
            await self.async_init()

        # Restore device-tracker entities saved from a previous run so we keep
        # reporting them (and apply consider_home) even before they reappear.
        entity_registry = er.async_get(self.hass)
        track_entries: list[RegistryEntry] = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        for entry in track_entries:
            if entry.domain == TRACKER_DOMAIN:
                self._devices[entry.unique_id] = ClientDevInfo(
                    entry.unique_id, entry.original_name
                )

        await self.renew_token()

    async def async_init(self) -> None:
        """Connect to the router and read its stable identity."""
        try:
            self._api = await self.get_api()
            await self._api.login(
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
        except OSError as exc:
            _LOGGER.exception("Error connecting to GL-iNet router %s", self._host)
            raise ConfigEntryNotReady from exc
        try:
            router_info = await self._update_platform(self._api.router_info)
            assert router_info is not None
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Error getting basic device info from GL-iNet router %s", self._host
            )
            raise ConfigEntryNotReady from exc

        _LOGGER.debug("Router info retrieved: %s", router_info)
        self._model = router_info[CONF_MODEL]
        self._sw_v = router_info["firmware_version"]
        self._factory_mac = router_info[CONF_MAC]
        self._late_init_complete = True

    async def get_api(self) -> GLinet:
        """Optimistically return a GLinet client, no test included."""
        conf = self.config_entry.data
        shared_session = async_get_clientsession(self.hass)
        ha_client = AiohttpClient(session=shared_session)

        if CONF_PASSWORD in conf:
            router = GLinet(
                sync=False, base_url=conf[CONF_HOST] + API_PATH, client=ha_client
            )
            await router.login(conf[CONF_USERNAME], conf[CONF_PASSWORD])
            return router
        _LOGGER.error(
            "Error setting up GL-iNet router, no auth details found in configuration"
        )
        raise ConfigEntryAuthFailed

    async def renew_token(self) -> None:
        """Attempt to get a new token."""
        try:
            await self._api.login(
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
            _LOGGER.info("GL-iNet router %s token was renewed", self._host)
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

    async def _async_update_data(self) -> GLinetData:
        """Fetch a fresh snapshot of router state."""
        self._cycle_failed = False
        status = await self._update_platform(self._api.router_get_status)
        if status is None:
            # The core health call failed (router unreachable / token not yet
            # recovered). Surface it so entities go unavailable; the token error
            # flag triggers a renewal attempt on the next cycle.
            raise UpdateFailed(f"Unable to reach GL-iNet router {self._host}")
        self._system_status = status.get("system", {})

        await self.update_device_trackers()
        await self.update_wifi_ifaces_state()
        await self.update_wireguard_client_state()
        await self.update_tailscale_state()

        # If any call hit a transport error this cycle, fail the whole refresh
        if self._cycle_failed:
            raise UpdateFailed(
                f"One or more calls to GL-iNet router {self._host} failed"
            )

        return GLinetData(
            system_status=self._system_status,
            devices=self._devices,
            connected_devices=self._connected_devices,
            wifi_ifaces=self._wifi_ifaces,
            wireguard_clients=self._wireguard_clients,
            wireguard_connections=self._wireguard_connections,
            tailscale_config=self._tailscale_config,
            tailscale_connection=self._tailscale_connection,
        )

    async def _update_platform(
        self, api_callable: Callable[[], Coroutine[Any, Any, T]]
    ) -> T | None:
        """Boilerplate to make update requests to api and handle errors."""
        # TODO: replace the hand-rolled _token_error/_connect_error recovery
        # with ConfigEntryAuthFailed (auth) + UpdateFailed (transport), letting
        # the coordinator handle retry/availability (the modern HA pattern).
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
            self._cycle_failed = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL-iNet router %s did not respond in time", self._host
                )
            return None
        except TokenError as exc:
            self._cycle_failed = True
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
            self._cycle_failed = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL-iNet router %s responded, but with an error code", self._host
                )
            return None
        except ConfigEntryAuthFailed:
            # Bubble up to Home Assistant to pause polling and trigger re-auth
            raise
        except Exception:  # pylint: disable=broad-except  # noqa: BLE001
            self._cycle_failed = True
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
        return response

    async def update_device_trackers(self) -> None:
        """Update the device trackers."""
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
        consider_home = self._options.get(
            CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
        )

        for device_mac, device in self._devices.items():
            dev_info = wrt_devices.get(device_mac)
            device.update(
                dev_info, consider_home, model=self._model, firmware=self._sw_v
            )

        for device_mac, dev_info in wrt_devices.items():
            if device_mac in self._devices:
                continue

            alias = dev_info.get("alias", "").strip()
            name = dev_info.get("name", "").strip()
            if not alias and not name:
                continue

            device = ClientDevInfo(device_mac)
            device.update(dev_info, model=self._model, firmware=self._sw_v)
            self._devices[device_mac] = device

        self._connected_devices = len(wrt_devices)

    async def update_wifi_ifaces_state(self) -> None:
        """Make a call to the API to get the WiFi ifaces config state."""
        ifaces = await self._update_platform(self._api.wifi_ifaces_get)
        if not ifaces:
            return
        # Rebuild the mapping each poll so an interface that disappears from the
        # router doesn't linger in the snapshot.
        self._wifi_ifaces = {
            name: WifiInterface(
                name=name,
                enabled=iface.get("enabled", False),
                ssid=iface.get("ssid", ""),
                guest=iface.get("guest", False),
                hidden=iface.get("hidden", False),
                encryption=iface.get("encryption", "UNKNOWN"),
            )
            for name, iface in ifaces.items()
        }

    async def update_tailscale_state(self) -> None:
        """Make a call to the API to get the tailscale state."""
        # tailscale_configured() is a plain API call (no _update_platform
        # wrapper), so guard it: a transient error must not abort the whole
        # refresh or escape uncaught.
        try:
            configured = await self._api.tailscale_configured()
        except (TimeoutError, NonZeroResponse, TokenError, OSError) as err:
            _LOGGER.debug("Could not determine tailscale state: %s", err)
            return
        if not configured:
            self._tailscale_config = {}
            return
        self._tailscale_config = (
            await self._update_platform(
                self._api._tailscale_get_config  # pylint: disable=protected-access  # noqa: SLF001
            )
            or {}
        )
        response: TailscaleConnection = await self._update_platform(
            self._api.tailscale_connection_state
        )
        self._tailscale_connection = response == TailscaleConnection.CONNECTED

    async def update_wireguard_client_state(self) -> None:
        """Make call to the API to get the wireguard client state."""
        response = await self._update_platform(self._api.wireguard_client_list)
        if not response:
            # No clients
            self._wireguard_clients = {}
            self._wireguard_connections = []
            return
        clients = {
            config["peer_id"]: WireGuardClient(
                name=config["name"],
                connected=False,
                group_id=config["group_id"],
                peer_id=config["peer_id"],
                tunnel_id=config.get("tunnel_id", None),
            )
            for config in response
        }
        connections: list[WireGuardClient] = []

        states = await self._update_platform(self._api.wireguard_client_state)
        for config in states or []:
            # OpenVPN configs are sometimes returned leading to errors.
            if config.get("type") != "wireguard":
                continue
            client = clients.get(config["peer_id"])
            if client is None:
                continue
            client.tunnel_id = config.get("tunnel_id", None)
            # 0 is disconnected, 1 is connected, 2 is connecting; if
            # config["enabled"] is false then status does not exist.
            client.connected = config.get("status", 0) != 0
            if client.connected:
                connections.append(client)

        self._wireguard_clients = clients
        self._wireguard_connections = connections

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.unique_id or self.factory_mac)},
            connections={
                (CONNECTION_NETWORK_MAC, format_mac(self.factory_mac)),
                (CONNECTION_NETWORK_MAC, adjust_mac(self.factory_mac, 1)),
            },
            name=self.device_name,
            model=self.model or "GL-iNet Router",
            manufacturer="GL-iNet",
            configuration_url=self._host,
            sw_version=self._sw_v,
        )

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

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
    def device_name(self) -> str:
        """Return the router's display name (used for the device registry)."""
        return f"GL-iNet {self._model.upper()}"


type GlinetConfigEntry = ConfigEntry[GLinetUpdateCoordinator]
