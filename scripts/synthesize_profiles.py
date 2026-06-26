#!/usr/bin/env python3
"""Generate synthesized router test profiles from the captured MT6000 fixtures.

The integration test suite runs every test against every "profile" directory
under ``tests/fixtures`` (see ``tests/conftest.py``). Only ``mt6000`` is a real,
sanitised capture; the other profiles are *derived* from it to exercise edge
cases we have no hardware for:

* ``mt6000_no_wireguard`` - a router with WireGuard absent
* ``mt6000_no_tailscale`` - a router with Tailscale absent
* ``mt3000_beryl_ax``     - a different, smaller model (dual-band, no VPN)
* ``wifi7_mlo_client``    - a client whose interface ``type`` index crashes the
                            integration today (regression guard, see below)

The generated JSON + ``profile.json`` files are committed, so the test suite
never runs this script. Re-run it only to regenerate the derived profiles after
the base ``mt6000`` capture changes, or to add a new edge case:

    python scripts/synthesize_profiles.py

Capture a *real* additional model with ``scripts/capture_fixtures.py`` instead;
those drop into ``tests/fixtures/<id>/`` and are picked up with no code changes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
BASE_ID = "mt6000"

# A legacy integer interface ``type`` code past the end of the resolver's index
# map (see custom_components/glinet/models.py). The interface resolver falls back
# to UNKNOWN for it rather than raising - this used to IndexError and crash setup.
OUT_OF_RANGE_INTERFACE_TYPE = 14


def load_base() -> dict[str, Any]:
    """Load every endpoint fixture from the base MT6000 profile."""
    base = FIXTURES / BASE_ID
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(base.glob("*.json"))
        if path.stem != "profile"
    }


def client_counts(connected_clients: dict[str, Any]) -> dict[str, int]:
    """Mirror the coordinator's named-client filter to derive expected counts."""
    tracked = 0
    for info in connected_clients.values():
        alias = (info.get("alias") or "").strip()
        name = (info.get("name") or "").strip()
        if alias or name:
            tracked += 1
    connected = len(connected_clients)
    return {
        "connected_client_count": connected,
        "tracked_device_count": tracked,
        "unnamed_client_count": connected - tracked,
    }


def write_profile(
    profile_id: str, files: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Write a profile directory: one JSON per endpoint plus profile.json."""
    profile_dir = FIXTURES / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Start clean so a removed endpoint (e.g. WireGuard) doesn't linger.
    for stale in profile_dir.glob("*.json"):
        stale.unlink()
    for name, data in files.items():
        _dump(profile_dir / f"{name}.json", data)
    _dump(profile_dir / "profile.json", manifest)
    print(f"wrote tests/fixtures/{profile_id}/ ({len(files)} endpoints)")


def _dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def no_wireguard(base: dict[str, Any]) -> None:
    """Build a profile with WireGuard absent: no client list/state endpoints."""
    files = copy.deepcopy(base)
    files.pop("wireguard_client_list", None)
    files.pop("wireguard_client_state", None)
    write_profile(
        "mt6000_no_wireguard",
        files,
        {
            "id": "mt6000_no_wireguard",
            "model": "MT6000",
            "firmware_version": "4.9.0",
            "factory_mac": "00:11:22:00:00:01",
            "title": "GL-iNet MT6000",
            "description": "Derived from mt6000 with WireGuard absent.",
            "capabilities": {
                "has_wireguard": False,
                "has_tailscale": True,
                "tailscale_connected": True,
            },
            "endpoints": {
                "tailscale_configured": True,
                "tailscale_connection_state": "CONNECTED",
            },
            "expected": {
                **client_counts(base["connected_clients"]),
                "wifi_iface_count": len(base["wifi_ifaces_get"]),
                "wireguard_client_count": 0,
                "wireguard_connection_count": 0,
            },
            "semantic": {
                "cpu_temp": "47",
                "load_avg1": "0.13",
                "uptime_seconds": 695435.84,
            },
        },
    )


def no_tailscale(base: dict[str, Any]) -> None:
    """Build a profile with Tailscale absent: tailscale_configured is False."""
    files = copy.deepcopy(base)
    files.pop("tailscale_get_config", None)
    write_profile(
        "mt6000_no_tailscale",
        files,
        {
            "id": "mt6000_no_tailscale",
            "model": "MT6000",
            "firmware_version": "4.9.0",
            "factory_mac": "00:11:22:00:00:01",
            "title": "GL-iNet MT6000",
            "description": "Derived from mt6000 with Tailscale absent.",
            "capabilities": {
                "has_wireguard": True,
                "has_tailscale": False,
                "tailscale_connected": False,
            },
            "endpoints": {"tailscale_configured": False},
            "expected": {
                **client_counts(base["connected_clients"]),
                "wifi_iface_count": len(base["wifi_ifaces_get"]),
                "wireguard_client_count": 1,
                "wireguard_connection_count": 1,
            },
            "semantic": {
                "cpu_temp": "47",
                "load_avg1": "0.13",
                "uptime_seconds": 695435.84,
            },
        },
    )


def beryl_ax(base: dict[str, Any]) -> None:
    """Build a different, smaller model: dual-band, no WireGuard or Tailscale."""
    files = copy.deepcopy(base)
    files.pop("wireguard_client_list", None)
    files.pop("wireguard_client_state", None)
    files.pop("tailscale_get_config", None)

    router_info = files["router_info"]
    router_info["model"] = "mt3000"
    router_info["firmware_version"] = "4.7.0"
    router_info["board_info"]["model"] = "GL.iNet GL-MT3000"
    router_info["mac"] = "00:11:22:00:03:01"

    # Beryl AX is dual-band with no guest/IoT radios in this synthetic capture.
    files["wifi_ifaces_get"] = {
        name: iface
        for name, iface in files["wifi_ifaces_get"].items()
        if name in {"wifi2g", "wifi5g"}
    }

    write_profile(
        "mt3000_beryl_ax",
        files,
        {
            "id": "mt3000_beryl_ax",
            "model": "MT3000",
            "firmware_version": "4.7.0",
            "factory_mac": "00:11:22:00:03:01",
            "title": "GL-iNet MT3000",
            "description": "Synthetic Beryl AX (MT3000): dual-band, no VPN.",
            "capabilities": {
                "has_wireguard": False,
                "has_tailscale": False,
                "tailscale_connected": False,
            },
            "endpoints": {"tailscale_configured": False},
            "expected": {
                **client_counts(files["connected_clients"]),
                "wifi_iface_count": len(files["wifi_ifaces_get"]),
                "wireguard_client_count": 0,
                "wireguard_connection_count": 0,
            },
            "semantic": {
                "cpu_temp": "47",
                "load_avg1": "0.13",
                "uptime_seconds": 695435.84,
            },
        },
    )


def wifi7_mlo_client(base: dict[str, Any]) -> None:
    """Build a profile with a WiFi7/MLO client (regression for the type crash)."""
    files = copy.deepcopy(base)
    # An MLO client whose self-describing iface resolves cleanly while its legacy
    # integer type is out of range - this used to crash setup with an IndexError.
    files["connected_clients"]["00:11:22:00:00:99"] = {
        "mac": "00:11:22:00:00:99",
        "name": "name-wifi7",
        "online": True,
        "type": OUT_OF_RANGE_INTERFACE_TYPE,
        "ip": "192.0.2.99",
        "iface": "MLO",
    }
    write_profile(
        "wifi7_mlo_client",
        files,
        {
            "id": "wifi7_mlo_client",
            "model": "MT6000",
            "firmware_version": "4.9.0",
            "factory_mac": "00:11:22:00:00:01",
            "title": "GL-iNet MT6000",
            "description": (
                "Derived from mt6000 with a WiFi7/MLO client (iface 'MLO', an "
                "out-of-range integer type). The interface resolver handles it "
                "without the historic IndexError."
            ),
            "capabilities": {
                "has_wireguard": True,
                "has_tailscale": True,
                "tailscale_connected": True,
            },
            "endpoints": {
                "tailscale_configured": True,
                "tailscale_connection_state": "CONNECTED",
            },
            "expected": {
                **client_counts(files["connected_clients"]),
                "wifi_iface_count": len(files["wifi_ifaces_get"]),
                "wireguard_client_count": 1,
                "wireguard_connection_count": 1,
            },
            "semantic": {
                "cpu_temp": "47",
                "load_avg1": "0.13",
                "uptime_seconds": 695435.84,
            },
        },
    )


def main() -> None:
    """Regenerate every derived profile from the base MT6000 capture."""
    base = load_base()
    no_wireguard(base)
    no_tailscale(base)
    beryl_ax(base)
    wifi7_mlo_client(base)


if __name__ == "__main__":
    main()
