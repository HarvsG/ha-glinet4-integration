"""Behavioural tests for GL-iNet sensors.

Entity values and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the behaviour snapshots can't express - the uptime-stability
regression and the filter that drops sensors a model doesn't report.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.coordinator import GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet_sensor/{mac}/system_{key}"
    )


async def _setup_at(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> GLinetUpdateCoordinator:
    """Set up the integration with the clock frozen and return the coordinator.

    Freezing before setup makes the uptime sensor's derived boot time
    deterministic across machines.
    """
    freezer.move_to("2026-01-01 00:00:00+00:00")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_uptime_is_stable_across_polls(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The uptime timestamp must not flap when uptime ticks within tolerance.

    Regression test: the old sensor recomputed ``now - uptime`` on every read,
    so the boot timestamp drifted across minute boundaries between polls.
    """
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    uptime_id = _entity_id(hass, profile.factory_mac, "uptime")
    assert uptime_id is not None
    first = hass.states.get(uptime_id).state
    assert first not in (None, "unknown", "unavailable")

    # Next poll: uptime ticks forward a few seconds (well within tolerance).
    status = profile.load("router_get_status")
    status["system"]["uptime"] += 7
    mock_glinet.router_get_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state == first


async def test_uptime_reanchors_on_reboot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A reboot (uptime resets low) moves the boot timestamp."""
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    uptime_id = _entity_id(hass, profile.factory_mac, "uptime")
    first = hass.states.get(uptime_id).state

    status = profile.load("router_get_status")
    status["system"]["uptime"] = 60.0  # just rebooted
    mock_glinet.router_get_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state != first


async def test_sensor_filtered_when_value_missing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A sensor whose value is unavailable on this model is not created."""
    status = profile.load("router_get_status")
    status["system"].pop("cpu", None)
    mock_glinet.router_get_status.return_value = status

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _entity_id(hass, profile.factory_mac, "cpu_temp") is None
    # A sensor with data is still created.
    assert _entity_id(hass, profile.factory_mac, "memory_use") is not None


async def test_load_average_zero_is_reported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A load average of exactly 0 is reported, not dropped as unavailable.

    Regression: the old value_fn short-circuited on the falsy 0 and the sensor
    went unavailable.
    """
    status = profile.load("router_get_status")
    status["system"]["load_average"] = [0, 0, 0]
    mock_glinet.router_get_status.return_value = status

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    load1 = _entity_id(hass, profile.factory_mac, "load_avg1")
    assert load1 is not None
    state = hass.states.get(load1).state
    assert state not in ("unavailable", "unknown")
    assert float(state) == 0
