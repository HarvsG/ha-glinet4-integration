"""Unit tests for randomized-MAC detection (issue #139 follow-up).

Exercises the pure helper in ``custom_components/glinet/utils.py``; no Home
Assistant runtime required (path set up in conftest.py).
"""

from __future__ import annotations

import pytest
from utils import is_randomized_mac


@pytest.mark.parametrize(
    "mac",
    [
        "9A:99:5B:9C:81:37",  # observed randomized phone
        "96:B9:1F:99:EA:79",  # observed randomized phone
        "02:00:00:00:00:00",
        "9a-99-5b-9c-81-37",  # hyphen separator, lower case
    ],
)
def test_randomized_macs(mac: str) -> None:
    """Locally-administered MACs are detected as randomized."""
    assert is_randomized_mac(mac) is True


@pytest.mark.parametrize(
    "mac",
    [
        "84:9E:56:B2:B2:57",  # real desktop NIC
        "1C:69:20:93:76:2B",  # real (SLZB-06)
        "00:06:78:B7:58:52",  # real (Home-Theater)
        "54:60:09:C0:70:B8",  # real (Chromecast)
    ],
)
def test_real_macs(mac: str) -> None:
    """Universally-administered (real hardware) MACs are not randomized."""
    assert is_randomized_mac(mac) is False


@pytest.mark.parametrize("mac", ["", "xx", "g", None])
def test_malformed_mac_is_safe(mac: str | None) -> None:
    """Malformed/missing input never raises and defaults to not-randomized."""
    assert is_randomized_mac(mac) is False
