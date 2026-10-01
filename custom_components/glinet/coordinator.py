"""DataUpdateCoordinators for the GL-iNet integration."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

import aiohttp
from gli4py.error_handling import APIClientError, NonZeroResponse

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL, SWITCH_SCAN_INTERVAL

if TYPE_CHECKING:
    from datetime import timedelta

    from gli4py.models import SystemStatusMetrics, WifiInterface

    from homeassistant.core import HomeAssistant

    from .router import ClientCounts, GLinetRouter, WireGuardClient
    from .wan import WanInterfaceState

_LOGGER = logging.getLogger(__name__)

MAX_CONSECUTIVE_AUTH_FAILURES = 3


@dataclass(slots=True)
class GLinetStatusData:
    """Status and client data fetched from the GL-iNet router."""

    system_status: SystemStatusMetrics
    wan_status: dict[str, WanInterfaceState]
    client_counts: ClientCounts


@dataclass(slots=True)
class GLinetSwitchData:
    """Switch state data fetched from the GL-iNet router."""

    wifi_ifaces: dict[str, WifiInterface]
    wireguard_connections: list[WireGuardClient] | None
    tailscale_connection: bool | None
    led_enabled: bool | None


class GLinetBaseCoordinator[T](DataUpdateCoordinator[T]):
    """Base coordinator for GL-iNet."""

    config_entry: GLinetConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GLinetConfigEntry,
        router: GLinetRouter,
        *,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({router.host}) {name}",
            update_interval=update_interval,
        )
        self.router = router
        self._consecutive_auth_errors: int = 0

    async def _async_update_data(self) -> T:
        """Fetch data from the router with common error handling."""
        try:
            data = await self._async_fetch_data()
            if not self.router.available:
                raise UpdateFailed(
                    f"Communication error with GL-iNet router {self.router.host}"
                )
        except ConfigEntryAuthFailed as exc:
            self._consecutive_auth_errors += 1
            if self._consecutive_auth_errors < MAX_CONSECUTIVE_AUTH_FAILURES:
                _LOGGER.info(
                    "GL-iNet router %s auth failed (attempt %d/%d); will retry before prompting re-authentication",
                    self.router.host,
                    self._consecutive_auth_errors,
                    MAX_CONSECUTIVE_AUTH_FAILURES,
                )
                raise UpdateFailed(
                    f"Authentication failed for {self.router.host} (attempt {self._consecutive_auth_errors}/{MAX_CONSECUTIVE_AUTH_FAILURES})"
                ) from exc
            _LOGGER.warning(
                "GL-iNet router %s failed authentication %d consecutive times; requesting re-authentication",
                self.router.host,
                self._consecutive_auth_errors,
            )
            self.config_entry.async_start_reauth(self.hass)
            raise
        except (
            TimeoutError,
            aiohttp.ClientError,
            OSError,
            NonZeroResponse,
            APIClientError,
        ) as exc:
            raise UpdateFailed(
                f"Error communicating with GL-iNet router {self.router.host}: {exc}"
            ) from exc

        self._consecutive_auth_errors = 0
        if not self.router.auth_failed:
            self.router.async_dismiss_reauth_flow()
        return data

    @abstractmethod
    async def _async_fetch_data(self) -> T:
        """Fetch data from the router (implemented by subclasses)."""


class GLinetStatusCoordinator(GLinetBaseCoordinator[GLinetStatusData]):
    """Coordinator to manage fetching GL-iNet status and client data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GLinetConfigEntry,
        router: GLinetRouter,
    ) -> None:
        """Initialize the status coordinator."""
        super().__init__(
            hass,
            entry,
            router,
            name="Status",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_fetch_data(self) -> GLinetStatusData:
        """Fetch status and client data from the router."""
        await self.router.update_system_status()
        await self.router.update_device_trackers()
        return GLinetStatusData(
            system_status=self.router.system_status,
            wan_status=self.router.wan_status,
            client_counts=self.router.client_counts,
        )


class GLinetSwitchCoordinator(GLinetBaseCoordinator[GLinetSwitchData]):
    """Coordinator to manage fetching GL-iNet switch data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GLinetConfigEntry,
        router: GLinetRouter,
    ) -> None:
        """Initialize the switch coordinator."""
        super().__init__(
            hass,
            entry,
            router,
            name="Switches",
            update_interval=SWITCH_SCAN_INTERVAL,
        )
        self._initial_fetch: bool = True

    def async_force_full_refresh(self) -> None:
        """Flag the next update to execute a full configuration re-probe."""
        self._initial_fetch = True

    async def _async_fetch_data(self) -> GLinetSwitchData:
        """Fetch switch data from the router."""
        # Wi-Fi interfaces polled on switch scan interval (60s)
        # If a user may have many switches, best to update in bulk
        await self.router.update_wifi_ifaces_state()

        # On initial fetch, probe configuration for optional endpoints
        if self._initial_fetch:
            self._initial_fetch = False
            # TODO detect all configured wireguard, openvpn, shadowsocks and
            # TOR clients & servers with router/vpn/status? and gen a switch for each
            await self.router.update_wireguard_client_list()
            # Tailscale configuration probe only runs at startup/full refresh
            # so non-configured endpoints are not polled frequently
            await self.router.update_tailscale_config()

        # Active connection states for configured services (polled each cycle if configured)
        if self.router.wireguard_clients:
            await self.router.update_wireguard_client_state()

        if self.router.tailscale_configured:
            await self.router.update_tailscale_connection_state()

        if self.router.led_supported:
            await self.router.update_led_state()

        return GLinetSwitchData(
            wifi_ifaces=self.router.wifi_ifaces,
            wireguard_connections=self.router.connected_wireguard_clients,
            tailscale_connection=self.router.tailscale_connection,
            led_enabled=self.router.led_enabled,
        )


@dataclass
class GLinetRuntimeData:
    """Runtime data for the GL-iNet integration."""

    router: GLinetRouter
    coordinator: GLinetStatusCoordinator
    switch_coordinator: GLinetSwitchCoordinator

    @property
    def status_coordinator(self) -> GLinetStatusCoordinator:
        """Alias for status coordinator."""
        return self.coordinator

    @property
    def data(self) -> GLinetStatusData:
        """Return status coordinator data for compatibility."""
        return self.coordinator.data

    async def async_refresh(self) -> None:
        """Refresh all coordinators."""
        await self.coordinator.async_refresh()
        await self.switch_coordinator.async_refresh()


type GLinetConfigEntry = ConfigEntry[GLinetRuntimeData]
