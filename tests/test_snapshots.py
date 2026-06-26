"""Snapshot every platform's entities for every router profile.

One parametrized test per platform loads *only* that platform and snapshots its
entity-registry entries and states via ``snapshot_platform``. The snapshots are
namespaced per profile by the parametrized node id (``[mt6000]`` etc.), so each
profile gets its own section in the ``.ambr`` files.

Regenerate after intentional entity changes with::

    uv run pytest tests/test_snapshots.py --snapshot-update
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

PLATFORMS = [
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("platform", PLATFORMS)
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    freezer: FrozenDateTimeFactory,
    platform: Platform,
) -> None:
    """Every platform's entities match the snapshot for every profile."""
    # Freeze time so the uptime sensor's derived boot timestamp is deterministic.
    freezer.move_to("2026-01-01 00:00:00+00:00")

    with patch("custom_components.glinet.PLATFORMS", [platform]):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)
