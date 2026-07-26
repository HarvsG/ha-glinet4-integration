"""Tests for the GL-iNet sensors."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.sensor import _uptime_calculation
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import MOCK_MAC, MOCK_STATUS, POLLED_METHODS

SENSOR_KEYS = (
    "cpu_temp",
    "load_avg1",
    "load_avg5",
    "load_avg15",
    "memory_use",
    "flash_use",
    "uptime",
)


def _entity_id(hass: HomeAssistant, key: str) -> str:
    """Resolve a sensor entity id from its unique id."""
    registry = er.async_get(hass)
    unique_id = f"glinet_sensor/{MOCK_MAC}/system_{key}"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 31
) -> None:
    """Advance frozen time and fire the polling interval."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_sensor_values(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test each system sensor reports the value from the API."""
    expected = {
        "cpu_temp": 42.5,
        "load_avg1": 0.25,
        "load_avg5": 0.5,
        "load_avg15": 1.0,
        "memory_use": 75.0,
        "flash_use": 10.0,
    }
    for key, value in expected.items():
        state = hass.states.get(_entity_id(hass, key))
        assert state is not None
        assert float(state.state) == pytest.approx(value)

    memory_state = hass.states.get(_entity_id(hass, "memory_use"))
    assert memory_state is not None
    assert memory_state.attributes["memory_total"] == 1_024_000
    assert memory_state.attributes["memory_free"] == 256_000


async def test_uptime_sensor(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    """Test the uptime sensor reports the boot time as a timestamp."""
    state = hass.states.get(_entity_id(hass, "uptime"))
    assert state is not None
    # Timestamp sensor states are truncated to whole seconds
    expected = (dt_util.utcnow() - timedelta(seconds=3600)).replace(microsecond=0)
    assert dt_util.parse_datetime(state.state) == expected


async def test_missing_cpu_temp_filters_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test a sensor the router does not report is not created."""
    status: dict[str, Any] = deepcopy(MOCK_STATUS)
    del status["system"]["cpu"]
    mock_api.router_get_status.side_effect = lambda *_a, **_kw: deepcopy(status)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"glinet_sensor/{MOCK_MAC}/system_cpu_temp"
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"glinet_sensor/{MOCK_MAC}/system_load_avg1"
        )
        is not None
    )


async def test_empty_first_status_keeps_all_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test sensors are still created when the first status poll is empty."""
    mock_api.router_get_status.side_effect = lambda *_a, **_kw: {}

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    for key in SENSOR_KEYS:
        state = hass.states.get(_entity_id(hass, key))
        assert state is not None
        assert state.state == STATE_UNKNOWN


def test_uptime_calculation_smoothing(freezer: FrozenDateTimeFactory) -> None:
    """Test small uptime deviations do not change the calculated boot time."""
    first = _uptime_calculation(3600.0, None)
    assert first == dt_util.utcnow() - timedelta(seconds=3600)

    # A deviation within 15 seconds keeps the previous boot time
    assert _uptime_calculation(3610.0, first) == first

    # A larger deviation produces a new boot time
    assert _uptime_calculation(3620.0, first) == dt_util.utcnow() - timedelta(
        seconds=3620
    )


async def test_uptime_moves_after_reboot(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test the uptime sensor reports a new boot time after a router reboot."""
    entity_id = _entity_id(hass, "uptime")
    state = hass.states.get(entity_id)
    assert state is not None
    initial = state.state

    status: dict[str, Any] = deepcopy(MOCK_STATUS)
    status["system"]["uptime"] = 5.0
    mock_api.router_get_status.side_effect = lambda *_a, **_kw: deepcopy(status)

    # Two ticks: one for the router poll to store the new uptime, one for
    # the entity poll to be certain to read it (both run on the same clock)
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state != initial
    expected = (dt_util.utcnow() - timedelta(seconds=5)).replace(microsecond=0)
    assert dt_util.parse_datetime(state.state) == expected


async def test_sensor_unavailable_on_connect_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    mock_api: MagicMock,
) -> None:
    """Test sensors become unavailable when the router is unreachable."""
    entity_id = _entity_id(hass, "cpu_temp")

    originals = {name: getattr(mock_api, name).side_effect for name in POLLED_METHODS}
    for name in POLLED_METHODS:
        getattr(mock_api, name).side_effect = TimeoutError
    # Two ticks: one for the router to latch the error, one for the entity
    # poll to pick it up (both run on the same clock)
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    for name, original in originals.items():
        getattr(mock_api, name).side_effect = original
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(42.5)
