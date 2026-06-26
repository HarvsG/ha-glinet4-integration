"""Behavioural tests for GL-iNet switches.

Switch states and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the side effects snapshots can't express - that toggling a
switch calls the right API and refreshes the coordinator. Feature-specific
switches are gated on the active profile's capabilities.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _switch_id(hass: HomeAssistant, mac: str, unique_suffix: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet_switch/{mac}/{unique_suffix}"
    )


async def test_wifi_switch_turn_on_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Toggling a WiFi switch calls the API and refreshes the coordinator."""
    entity_id = _switch_id(hass, profile.factory_mac, "iface_wifi2g")
    assert entity_id is not None
    calls_before = mock_glinet.wifi_ifaces_get.await_count

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", False)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", True)

    # async_request_refresh after each toggle re-polls the interfaces (the
    # refresh is debounced, so let it run before asserting).
    await hass.async_block_till_done()
    assert mock_glinet.wifi_ifaces_get.await_count > calls_before


async def test_tailscale_switch_turn_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Turning off the Tailscale switch stops Tailscale."""
    if not profile.manifest["capabilities"]["has_tailscale"]:
        pytest.skip("profile has no Tailscale")
    entity_id = _switch_id(hass, profile.factory_mac, "tailscale")
    assert entity_id is not None

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.tailscale_stop.assert_awaited()


async def test_wireguard_switch_turn_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Turning off the WireGuard switch stops the client."""
    if not profile.manifest["capabilities"]["has_wireguard"]:
        pytest.skip("profile has no WireGuard")
    client_name = profile.load("wireguard_client_list")[0]["name"]
    entity_id = _switch_id(hass, profile.factory_mac, f"{client_name}/wireguard_client")
    assert entity_id is not None

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wireguard_client_stop.assert_awaited()
