"""Pytest setup: make the integration's HA-free helpers importable.

``custom_components/glinet/utils.py`` has no Home Assistant dependencies, so we
add the package directory to ``sys.path`` to unit test it in isolation.
"""

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "custom_components" / "glinet"),
)
