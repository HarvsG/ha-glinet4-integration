"""Diagnostics support for the GL-iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_MAC, CONF_PASSWORD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .router import GLinetConfigEntry

# Entries created before 0.2.0 may still carry a stale api_token
TO_REDACT = {CONF_PASSWORD, CONF_API_TOKEN, CONF_MAC}


async def async_get_config_entry_diagnostics(
    _: HomeAssistant, entry: GLinetConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    router = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "router": {
            "model": router.model,
            "firmware_version": router.sw_version,
            "available": router.available,
            "connected_devices_count": router.connected_devices_count,
            "wifi_ifaces": [
                {
                    "name": iface.name,
                    "enabled": iface.enabled,
                    "guest": iface.guest,
                    "hidden": iface.hidden,
                    "encryption": iface.encryption,
                    "ssid": REDACTED,
                }
                for iface in router.wifi_ifaces.values()
            ],
            "wireguard_clients": [
                {"name": client.name, "connected": client.connected}
                for client in router.wireguard_clients.values()
            ],
            "tailscale_configured": router.tailscale_configured,
            "tailscale_connected": router.tailscale_connection,
            "system_status": router.system_status,
        },
    }
