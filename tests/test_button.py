"""Tests for the GL-iNet reboot button."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


async def test_reboot_button_presses_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Pressing the reboot button calls the router reboot endpoint."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"glinet_button/{profile.factory_mac}/reboot"
    )
    assert entity_id is not None

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.router_reboot.assert_awaited_once()
