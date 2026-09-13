"""Tests for the GL-iNet diagnostics."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .const import MOCK_HOST


async def test_diagnostics_redaction(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Test the diagnostics redact secrets and include router state."""
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, init_integration
    )

    entry = diagnostics["entry"]
    assert entry["data"]["password"] == REDACTED
    assert entry["data"]["host"] == MOCK_HOST
    assert entry["options"]["consider_home"] == 180

    router = diagnostics["router"]
    assert router["model"] == "MT6000"
    assert router["firmware_version"] == "4.8.2"
    assert router["available"] is True
    assert router["connected_devices_count"] == 2
    assert all(iface["ssid"] == REDACTED for iface in router["wifi_ifaces"])
    assert {client["name"] for client in router["wireguard_clients"]} == {
        "wg_home",
        "wg_office",
    }
    assert router["tailscale_configured"] is True
    assert router["tailscale_connected"] is True
    assert router["system_status"]["uptime"] == 3600.0
