"""Represent the GLinet router."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, Self, TypeVar

import aiohttp
from gli4py import GLinet
from gli4py.error_handling import (
    APIClientError,
    AuthenticationError,
    NonZeroResponse,
    TokenError,
)
from gli4py.models import (
    LedConfigResponse,
    RouterStatusResponse,
    SystemStatusMetrics,
    SystemStatusNetwork,
    TailscaleConnection,
)
from uplink import AiohttpClient

from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DOMAIN as TRACKER_DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    API_PATH,
    CONF_TRACK_RANDOMIZED_MAC,
    DEFAULT_TRACK_RANDOMIZED_MAC,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    TRACK_RANDOMIZED_MAC_IGNORE,
)
from .utils import adjust_mac, is_randomized_mac, is_ssl_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from gli4py.models import ClientEntry, TailscaleConfigResponse, WifiInterface

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry

    from .coordinator import GLinetConfigEntry

_LOGGER = logging.getLogger(__name__)
REBOOT_GRACE_PERIOD: int = 90
T = TypeVar("T")


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

# Interface types grouped for the connected-client breakdown counts.
_GUEST_INTERFACE_TYPES: frozenset[DeviceInterfaceType] = frozenset(
    {
        DeviceInterfaceType.WIFI_24_GUEST,
        DeviceInterfaceType.WIFI_5_GUEST,
        DeviceInterfaceType.WIFI_6_GUEST,
        DeviceInterfaceType.MLO_GUEST,
    }
)
_WIRELESS_INTERFACE_TYPES: frozenset[DeviceInterfaceType] = frozenset(
    {
        DeviceInterfaceType.WIFI_24,
        DeviceInterfaceType.WIFI_5,
        DeviceInterfaceType.WIFI_6,
        DeviceInterfaceType.MLO,
    }
)


@dataclass(frozen=True)
class ClientCounts:
    """Counts of currently-connected clients grouped by connection type."""

    total: int = 0
    wired: int = 0
    wireless: int = 0
    guest: int = 0


def _count_clients_by_type(
    clients: dict[str, ClientEntry],
) -> ClientCounts:
    """Group connected clients into wired / wireless / guest counts."""
    wired = wireless = guest = 0
    for client in clients.values():
        if not client.online:
            continue
        iface_type = DEVICE_INTERFACE_TYPE_MAP.get(
            client.type, DeviceInterfaceType.UNKNOWN
        )
        if iface_type == DeviceInterfaceType.LAN:
            wired += 1
        elif iface_type in _GUEST_INTERFACE_TYPES:
            guest += 1
        elif iface_type in _WIRELESS_INTERFACE_TYPES:
            wireless += 1
    return ClientCounts(
        total=wired + wireless + guest, wired=wired, wireless=wireless, guest=guest
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class GLinetOptions:
    """Options for GL-iNet router."""

    consider_home: float
    track_randomized_mac: str
    verify_ssl: bool

    @classmethod
    def from_entry(cls, entry: ConfigEntry[Any]) -> Self:
        """Create options from config entry, falling back to data for backward compatibility."""
        return cls(
            consider_home=float(
                entry.options.get(
                    CONF_CONSIDER_HOME,
                    entry.data.get(
                        CONF_CONSIDER_HOME,
                        DEFAULT_CONSIDER_HOME.total_seconds(),
                    ),
                )
            ),
            track_randomized_mac=str(
                entry.options.get(
                    CONF_TRACK_RANDOMIZED_MAC,
                    entry.data.get(
                        CONF_TRACK_RANDOMIZED_MAC,
                        DEFAULT_TRACK_RANDOMIZED_MAC,
                    ),
                )
            ),
            verify_ssl=bool(
                entry.options.get(
                    CONF_VERIFY_SSL,
                    entry.data.get(
                        CONF_VERIFY_SSL,
                        DEFAULT_VERIFY_SSL,
                    ),
                )
            ),
        )


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
        self._options: GLinetOptions = GLinetOptions.from_entry(entry)
        self._consider_home: float = self._options.consider_home

        # gli4py API
        self._api: GLinet
        self._host: str = entry.data[CONF_HOST]

        # Stable properties
        self._factory_mac: str = "UNKNOWN"
        self._model: str = "UNKNOWN"
        self._sw_v: str = "UNKNOWN"

        # State
        self._devices: dict[str, ClientDevInfo] = {}
        self._client_counts: ClientCounts = ClientCounts()
        self._wifi_ifaces: dict[str, WifiInterface] = {}
        self._system_status: SystemStatusMetrics = SystemStatusMetrics()
        self._wireguard_clients: dict[int, WireGuardClient] = {}
        self._wireguard_connections: list[WireGuardClient] | None = None
        self._tailscale_config: TailscaleConfigResponse | None = None
        self._tailscale_connection: bool | None = None
        self._led_enable: bool | None = None
        self._led_supported: bool = False
        self._wan_status: dict[str, SystemStatusNetwork] = {}
        self._known_wan_interfaces: set[str] = set()
        self._warned_wan_interfaces: set[str] = set()

        # Flow control
        self._late_init_complete: bool = False
        self._connect_error: bool = False
        self._auth_failed: bool = False
        self._consecutive_auth_errors: int = 0

    async def async_init(self) -> None:
        """Set up a GL-iNet router.

        Do some late initialization
        """

        # Store an API object for platforms to access
        self._api = self._create_api()
        try:
            await self.renew_token()
        except ConfigEntryAuthFailed:
            raise
        except Exception as exc:
            if is_ssl_error(exc):
                raise ConfigEntryNotReady(
                    f"SSL certificate verification failed for GL-iNet router {self._host}. "
                    "If using a self-signed certificate, disable SSL verification in integration options or reconfiguration"
                ) from exc
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
        self._model = router_info["model"]
        self._sw_v = router_info["firmware_version"]
        self._factory_mac = router_info["mac"]

        await self._async_detect_led_support()

        self._late_init_complete = True

    async def setup(self) -> None:
        """Load in saved tracker entities from the registry."""

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
                    entry.unique_id, entry.name or entry.original_name
                )

    @callback
    def async_dismiss_reauth_flow(self) -> None:
        """Dismiss any active reauth flow for this entry if communication recovered."""
        for flow in self._entry.async_get_active_flows(self.hass, {SOURCE_REAUTH}):
            self.hass.config_entries.flow.async_abort(flow["flow_id"])

    def _create_api(self) -> GLinet:
        """Optimistically return a GLinet object for connection to the API, no test included."""
        conf = self._entry.data
        shared_session = async_get_clientsession(
            self.hass, verify_ssl=self._options.verify_ssl
        )
        ha_client = AiohttpClient(session=shared_session)

        if CONF_PASSWORD in conf:
            return GLinet(
                sync=False, base_url=conf[CONF_HOST] + API_PATH, client=ha_client
            )
        _LOGGER.error(
            "Error setting up GL-iNet router, no auth details found in configuration"
        )
        raise ConfigEntryError("No auth details found in configuration")

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
            self._auth_failed = False
            self._consecutive_auth_errors = 0
            self.async_dismiss_reauth_flow()
        except TokenError as exc:
            _LOGGER.warning(
                "GL-iNet %s session token was refused or expired: %s; will retry",
                self._host,
                exc,
            )
            self._connect_error = True
            raise
        except AuthenticationError as exc:
            self._auth_failed = True
            _LOGGER.exception(
                "GL-iNet %s failed to renew the token with an authentication error, have you changed your router password?",
                self._host,
            )
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            if is_ssl_error(exc):
                _LOGGER.warning(
                    "SSL certificate verification failed for GL-iNet router %s. "
                    "If using a self-signed certificate, disable SSL verification in the integration options or reconfiguration",
                    self._host,
                )
            else:
                _LOGGER.warning(
                    "Could not connect to GL-iNet router to renew token: %s", exc
                )
            raise  # Let generic network/timeout exceptions bubble up normally

    async def _update_platform(
        self, api_callable: Callable[[], Awaitable[T]]
    ) -> T | None:
        """Boilerplate to make update requests to api and handle errors."""
        if self._auth_failed:
            await self.renew_token()

        try:
            _LOGGER.debug(
                "Making api call %s from _update_platform()", api_callable.__name__
            )
            response = await api_callable()
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            if not self._connect_error:
                self._connect_error = True
                if isinstance(exc, TimeoutError):
                    _LOGGER.warning(
                        "GL-iNet router %s did not respond in time",
                        self._host,
                    )
                else:
                    _LOGGER.warning(
                        "GL-iNet router %s communication error: %s",
                        self._host,
                        exc,
                    )
            return None
        except TokenError as exc:
            _LOGGER.debug(
                "GL-iNet router %s session token was refused or expired (%s); renewing token and retrying",
                self._host,
                exc,
            )
            try:
                await self.renew_token()
                response = await api_callable()
            except TimeoutError, aiohttp.ClientError, OSError, NonZeroResponse:
                self._connect_error = True
                return None
        except AuthenticationError as exc:
            self._connect_error = True
            _LOGGER.warning(
                "GL-iNet router %s authentication failed (%s); attempting to renew token",
                self._host,
                exc,
            )
            try:
                await self.renew_token()
                response = await api_callable()
            except TimeoutError, aiohttp.ClientError, OSError, NonZeroResponse:
                return None
        except NonZeroResponse:
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.warning(
                    "GL-iNet router %s responded, but with an error code", self._host
                )
            return None
        except ConfigEntryAuthFailed:
            # Let async_setup_entry (startup) or update_states (polling) handle reauth
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

        if self._connect_error:
            self._connect_error = False
            _LOGGER.info("Reconnected to Gl-inet router %s", self._host)
        if response is not None:
            self._auth_failed = False
        _LOGGER.debug(
            "_update_platform() completed without error for callable %s, returning response: %s",
            api_callable.__name__,
            str(response)[:200],
        )
        return response

    async def update_system_status(self) -> None:
        """Update the system status and WAN interface states from the API."""
        status: RouterStatusResponse | None = await self._update_platform(
            self._api.router_get_status
        )
        if not status:
            return
        self._system_status = status.system
        self._wan_status = {network.interface: network for network in status.network}
        currently_up = {
            name for name, network in self._wan_status.items() if network.up
        }
        new_to_register = currently_up - self._known_wan_interfaces
        if new_to_register:
            self._known_wan_interfaces.update(new_to_register)

    async def update_device_trackers(self) -> None:
        """Update the device trackers."""

        all_clients = await self._update_platform(self._api.all_clients)
        if all_clients is None:
            return

        all_clients_by_mac = {mac.lower(): dev for mac, dev in all_clients.items()}

        uptime = self._system_status.uptime if self._system_status else None
        if (
            not all_clients
            and uptime is not None
            and uptime < REBOOT_GRACE_PERIOD
            and self._devices
        ):
            _LOGGER.debug(
                "Ignoring empty client list during post-reboot startup (uptime %ss)",
                uptime,
            )
            return

        _LOGGER.debug(
            "update_device_trackers returned %d device(s): %s",
            len(all_clients),
            list(all_clients.keys()),
        )

        registry = er.async_get(self.hass)
        devices_by_lower = {
            mac.lower(): device for mac, device in self._devices.items()
        }
        for device_mac, device in list(self._devices.items()):
            dev_info = all_clients_by_mac.get(device_mac.lower())
            device.update(dev_info, self._consider_home)
            if (
                dev_info is None
                and not device.is_connected
                and not device.available
                and not registry.async_get_entity_id(TRACKER_DOMAIN, DOMAIN, device_mac)
            ):
                del self._devices[device_mac]

        for device_mac, dev_info in all_clients.items():
            # Skip if we already have this device
            if device_mac.lower() in devices_by_lower or device_mac in self._devices:
                continue

            # Optionally ignore clients using MAC randomization entirely
            if (
                self.randomized_mac_mode == TRACK_RANDOMIZED_MAC_IGNORE
                and is_randomized_mac(device_mac)
            ):
                continue

            device = ClientDevInfo(device_mac)
            device.update(dev_info)
            self._devices[device_mac] = device
            _LOGGER.debug(
                "Discovered new tracked device %s (name=%r alias=%r)",
                device_mac,
                dev_info.name if dev_info else None,
                dev_info.alias if dev_info else None,
            )

        self._client_counts = _count_clients_by_type(all_clients)

    async def update_wifi_ifaces_state(self) -> None:
        """Make a call to the API to get the WiFi ifaces config state."""
        ifaces = await self._update_platform(self._api.wifi_ifaces_get)
        if not ifaces:
            return
        self._wifi_ifaces = ifaces

    async def update_led_state(self) -> None:
        """Make a call to the API to get the LED indicator state."""
        config: LedConfigResponse | None = await self._update_platform(
            self._api.led_get_config
        )
        if config is None:
            return
        self._led_enable = config.led_enable

    async def _async_detect_led_support(self) -> None:
        """Probe the LED endpoint once to decide whether to expose the LED switch.

        An unsupported endpoint (APIClientError) simply omits the switch. A
        network-level failure is treated as a setup failure so Home Assistant
        retries, rather than permanently marking the router as unsupported.
        """
        try:
            config = await self._api.led_get_config()
        except APIClientError:
            # TODO update to MethodNotFound error or similar
            _LOGGER.debug("Router %s does not report LED support", self._host)
            self._led_supported = False
            return
        except (OSError, aiohttp.ClientError, TimeoutError) as exc:
            raise ConfigEntryNotReady(
                f"Error probing LED support on {self._host}"
            ) from exc
        self._led_supported = True
        self._led_enable = config.led_enable

    async def update_tailscale_config(self) -> None:
        """Make a call to the API to check tailscale configuration and details."""
        configured = await self._update_platform(self._api.tailscale_configured)
        if configured is None:
            # The request failed - keep the previous state
            return
        if not configured:
            self._tailscale_config = None
            self._tailscale_connection = None
            return
        # TODO this is a placeholder that needs to be replaced with a pulic method that combines useful info in _tailscale_status and _tailscale_get_config
        config_response = await self._update_platform(
            self._api._tailscale_get_config  # pylint: disable=protected-access  # noqa: SLF001
        )
        if config_response is None:
            # The request failed - keep the previous state
            return
        if config_response:
            self._tailscale_config = config_response
        else:
            self._tailscale_config = None

    async def update_tailscale_connection_state(self) -> None:
        """Make a call to the API to get tailscale connection state."""
        if not self.tailscale_configured:
            self._tailscale_connection = None
            return
        state: TailscaleConnection | None = await self._update_platform(
            self._api.tailscale_connection_state
        )
        if state is None:
            # The request failed - keep the previous state
            return
        self._tailscale_connection = state == TailscaleConnection.CONNECTED

    async def update_tailscale_state(self) -> None:
        """Make a call to the API to get the tailscale state."""
        await self.update_tailscale_config()
        if self.tailscale_configured:
            await self.update_tailscale_connection_state()

    async def update_wireguard_client_list(self) -> None:
        """Make call to the API to get the wireguard client profiles list."""
        response = await self._update_platform(self._api.wireguard_client_list)
        if not response:
            return
        for config in response:
            name = config.name
            peer_id = config.peer_id
            group_id = config.group_id
            raw_tunnel_id = config.tunnel_id
            tunnel_id = raw_tunnel_id if isinstance(raw_tunnel_id, int) else None
            if tunnel_id is not None:
                _LOGGER.warning(
                    "WireGuard client %s has tunnel_id %s, tunnel_id is poorly documented and is planned to be deprecated so if you see this message please report it to the integration author at https://github.com/HarvsG/ha-glinet4-integration/issues with router model %s and firmware version %s",
                    name,
                    tunnel_id,
                    self.model,
                    self.sw_version,
                )
            if not name or not peer_id or not group_id:
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
                tunnel_id=tunnel_id,
            )

    async def update_wireguard_connection_state(self) -> None:
        """Update whether the currently selected WG client is connected."""
        if len(self._wireguard_clients) == 0:
            _LOGGER.debug("No wireguard clients, there is nothing to update")
            return

        # update whether the currently selected WG client is connected
        status_response = await self._update_platform(self._api.wireguard_client_state)
        if not status_response:
            return
        # 0 is disconnted, 1 is connected, 2 is connecting
        self._wireguard_connections = []
        for status_item in status_response:
            # if status_item.enabled is false then status does not exist
            connected: bool = status_item.status != 0

            client = self._wireguard_clients.get(status_item.peer_id)
            if client is None:
                continue
            client.tunnel_id = status_item.tunnel_id
            client.connected = connected
            if connected:
                # If more modern firmware supports more than 1 client being connected, we need to change this
                self._wireguard_connections.append(client)

    async def update_wireguard_client_state(self) -> None:
        """Make call to the API to get the wireguard client state."""
        await self.update_wireguard_client_list()
        await self.update_wireguard_connection_state()

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
    def options(self) -> GLinetOptions:
        """Return router options."""
        return self._options

    @property
    def randomized_mac_mode(self) -> str:
        """How clients using MAC randomization should be tracked."""
        return self._options.track_randomized_mac

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
    def auth_failed(self) -> bool:
        """Return True when authentication with the router has failed."""
        return self._auth_failed

    @property
    def connected_devices_count(self) -> int:
        """Return the number of currently connected client devices."""
        return self._client_counts.total

    @property
    def client_counts(self) -> ClientCounts:
        """Return connected-client counts grouped by connection type."""
        return self._client_counts

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
    def led_enabled(self) -> bool | None:
        """Return whether the router LED indicators are enabled."""
        return self._led_enable

    @property
    def led_supported(self) -> bool:
        """Return whether the router supports LED control."""
        return self._led_supported

    @property
    def wireguard_clients(self) -> dict[int, WireGuardClient]:
        """Return router wireguard clients."""
        return self._wireguard_clients

    @property
    def connected_wireguard_clients(self) -> None | list[WireGuardClient]:
        """Return the wireguard clients that are connected, if any."""
        return self._wireguard_connections

    @property
    def tailscale_configured(self) -> bool:
        """Is tailscale configured."""
        return self._tailscale_config is not None

    @property
    def tailscale_connection(self) -> bool | None:
        """Property for tailscale connection."""
        if not self.tailscale_configured:
            return None
        return self._tailscale_connection

    @property
    def tailscale_config(self) -> TailscaleConfigResponse | None:
        """Property for tailscale connection."""
        # TODO, we need a non private API method that returns some useful config info
        return self._tailscale_config

    @property
    def system_status(self) -> SystemStatusMetrics:
        """Property for system status."""

        return self._system_status

    @property
    def wan_status(self) -> dict[str, SystemStatusNetwork]:
        """Return the latest WAN interface states keyed by interface name."""
        return self._wan_status

    def register_known_wan_interfaces(self, interfaces: set[str]) -> None:
        """Mark interfaces as already-registered so we don't fire signal_wan_new for them."""
        self._known_wan_interfaces.update(interfaces)


@dataclass
class WireGuardClient:
    """Class for keeping track of WireGuard Client Configs."""

    # TODO could we deprecate this class and use WireguardClientListItem or WireguardStatusItem instead?
    name: str
    connected: bool = field(compare=False)
    group_id: int
    peer_id: int
    tunnel_id: int | None = None


class ClientDevInfo:
    """Representation of a device connected to the router."""

    def __init__(self, mac: str, name: str | None = None) -> None:
        """Initialize a connected device."""
        self._mac: str = mac
        self._name: str | None = name
        self._ip_address: str | None = None
        self._last_activity: datetime = dt_util.utcnow() - timedelta(days=1)
        self._connected: bool = False
        self._available: bool = True
        self._if_type: DeviceInterfaceType = DeviceInterfaceType.UNKNOWN

    def update(
        self,
        dev_info: ClientEntry | None = None,
        consider_home: float = 0,
    ) -> None:
        """Update connected device info."""
        now: datetime = dt_util.utcnow()
        if dev_info:
            self._available = True
            # Prefer the user-defined alias as a name
            alias = dev_info.alias
            if alias and alias.strip():
                self._name = alias
            else:
                # If no alias, fallback to auto-assigned name field
                name = dev_info.name
                if name and name.strip() and name != "*":
                    self._name = name
                elif not self._name:
                    self._name = self._mac.replace(":", "_")

            if dev_info.ip:
                self._ip_address = dev_info.ip

            if dev_info.online:
                self._last_activity = now
                self._connected = True
            elif self._connected:
                self._connected = (
                    now - self._last_activity
                ).total_seconds() < consider_home
            else:
                self._connected = False

            self._if_type = DEVICE_INTERFACE_TYPE_MAP.get(
                dev_info.type, DeviceInterfaceType.UNKNOWN
            )
        elif self._connected:
            # dev_info is None (device completely omitted from router response)
            self._connected = (
                now - self._last_activity
            ).total_seconds() < consider_home
            self._available = self._connected
            if not self._connected:
                self._ip_address = None
        else:
            self._connected = False
            self._available = False
            self._ip_address = None

    @property
    def available(self) -> bool:
        """Return available status."""
        return self._available

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
