"""DataUpdateCoordinator for the GL-iNet integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from gli4py.error_handling import APIClientError, NonZeroResponse

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL

if TYPE_CHECKING:
    from gli4py.models import (
        SystemStatusMetrics,
        TailscaleConfigResponse,
        WifiInterface,
    )

    from homeassistant.core import HomeAssistant

    from .router import ClientCounts, GLinetRouter, WireGuardClient
    from .wan import WanInterfaceState

_LOGGER = logging.getLogger(__name__)

MAX_CONSECUTIVE_AUTH_FAILURES = 3

# PEP 695 type aliases are evaluated lazily, so the forward
# reference to GLinetDataUpdateCoordinator is resolved when first used
type GLinetConfigEntry = ConfigEntry[GLinetDataUpdateCoordinator]


@dataclass(slots=True)
class GLinetData:
    """Data fetched from the GL-iNet router."""

    system_status: SystemStatusMetrics
    wan_status: dict[str, WanInterfaceState]
    client_counts: ClientCounts
    wifi_ifaces: dict[str, WifiInterface]
    wireguard_clients: dict[int, WireGuardClient]
    wireguard_connections: list[WireGuardClient] | None
    tailscale_config: TailscaleConfigResponse | None
    tailscale_connection: bool | None
    led_enabled: bool | None


class GLinetDataUpdateCoordinator(DataUpdateCoordinator[GLinetData]):
    """Coordinator to manage fetching GL-iNet router data."""

    config_entry: GLinetConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GLinetConfigEntry,
        router: GLinetRouter,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({router.host})",
            update_interval=SCAN_INTERVAL,
        )
        self.router = router
        self._consecutive_auth_errors: int = 0
        self._force_full_update: bool = False

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying router for compatibility."""
        return getattr(self.router, name)

    def async_force_full_refresh(self) -> None:
        """Flag the next update to execute a full tiered refresh."""
        self._force_full_update = True

    async def _async_update_data(self) -> GLinetData:
        """Fetch all data from the router."""
        full_update = self._force_full_update
        self._force_full_update = False
        try:
            data = await self.router.async_fetch_all(full_update=full_update)
        except ConfigEntryAuthFailed as exc:
            self._consecutive_auth_errors += 1
            if self._consecutive_auth_errors < MAX_CONSECUTIVE_AUTH_FAILURES:
                _LOGGER.warning(
                    "GL-iNet router %s auth failed (attempt %d/%d); will retry before prompting re-authentication",
                    self.router.host,
                    self._consecutive_auth_errors,
                    MAX_CONSECUTIVE_AUTH_FAILURES,
                )
                raise UpdateFailed(
                    f"Authentication failed for {self.router.host} (attempt {self._consecutive_auth_errors}/{MAX_CONSECUTIVE_AUTH_FAILURES})"
                ) from exc
            _LOGGER.error(  # noqa: TRY400
                "GL-iNet router %s failed authentication %d consecutive times; requesting re-authentication",
                self.router.host,
                self._consecutive_auth_errors,
            )
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
        self.router.async_dismiss_reauth_flow()
        return data
