#!/usr/bin/env python3
"""Capture and sanitise a router's API responses into a test profile.

Connects to a live GL-iNet router, calls the read-only endpoints the
integration uses, deterministically sanitises the responses (MACs, IPs, SSIDs,
hostnames and secrets), and writes a profile directory under ``tests/fixtures``
that the test suite picks up automatically (see ``tests/conftest.py``).

    GLINET_PASSWORD=... python scripts/capture_fixtures.py \
        --host http://192.168.8.1 --username root --profile-id flint3

Only read-only endpoints are called; no router state is changed. The sanitiser
is a pure function (``sanitise``) covered by ``tests/test_capture_fixtures.py``
so it cannot silently leak real MACs/IPs/secrets into a committed fixture.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any

from gli4py import GLinet
from gli4py.enums import TailscaleConnection
from uplink import AiohttpClient

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
API_PATH = "/rpc"

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Keys whose values are secrets or stable hardware identifiers: redact outright.
REDACT_KEYS = frozenset(
    {
        "architecture",
        "cellular_ref",
        "country_code",
        "ddns",
        "firmware_date",
        "firmware_type",
        "kernel_version",
        "key",
        "lan",
        "minimum_temperature",
        "openwrt_version",
        "password",
        "psk",
        "radio",
        "reset_button",
        "sid",
        "silkprint",
        "slot",
        "sn",
        "sn_bak",
        "token",
        "usb",
        "usb3",
        "usb_reset",
        "vendor",
        "wan",
    }
)
# Keys whose values are free text that may identify a person or network: replace
# with a stable placeholder. Categorical values (model, encryption, type, ...)
# are deliberately preserved so model/firmware differences stay testable.
SSID_KEYS = frozenset({"ssid"})
NAME_KEYS = frozenset({"name", "alias", "hostname"})


@dataclass
class Sanitiser:
    """Stateful, deterministic sanitiser shared across every endpoint."""

    mac_map: dict[str, str] = field(default_factory=dict)
    ip_map: dict[str, str] = field(default_factory=dict)
    text_map: dict[str, str] = field(default_factory=dict)

    def seed_router_mac(self, router_info: dict[str, Any]) -> None:
        """Map the router's own MAC first so it is always ...:00:01."""
        mac = router_info.get("mac")
        if isinstance(mac, str) and MAC_RE.match(mac):
            self._mac(mac)

    def _mac(self, value: str) -> str:
        if value not in self.mac_map:
            index = len(self.mac_map) + 1
            self.mac_map[value] = f"00:11:22:00:00:{index:02x}"
        return self.mac_map[value]

    def _ip(self, value: str) -> str:
        if value not in self.ip_map:
            self.ip_map[value] = f"192.0.2.{len(self.ip_map) + 1}"
        return self.ip_map[value]

    def _text(self, value: str, prefix: str) -> str:
        if value not in self.text_map:
            self.text_map[value] = f"{prefix}-{len(self.text_map) + 1}"
        return self.text_map[value]

    def value(self, value: Any, key: str | None = None) -> Any:
        """Return a sanitised copy of an arbitrary JSON value."""
        if isinstance(value, dict):
            return {
                self._key(name): self.value(item, name) for name, item in value.items()
            }
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, str):
            return self._string(value, key)
        return value

    def _key(self, name: str) -> str:
        """Sanitise a dict key (connected_clients is keyed by client MAC)."""
        if MAC_RE.match(name):
            return self._mac(name)
        return name

    def _string(self, value: str, key: str | None) -> str:
        if key in REDACT_KEYS:
            return "REDACTED" if value else value
        if MAC_RE.match(value):
            return self._mac(value)
        if IPV4_RE.match(value):
            return self._ip(value)
        if key in SSID_KEYS and value:
            return self._text(value, "ssid")
        if key in NAME_KEYS and value not in ("", "*"):
            return self._text(value, "name" if key != "hostname" else "hostname")
        return value


def sanitise(payload: Any, sanitiser: Sanitiser, key: str | None = None) -> Any:
    """Return a deterministically sanitised copy of ``payload``."""
    return sanitiser.value(payload, key)


async def fetch_raw(api: GLinet) -> dict[str, Any]:
    """Call the read-only endpoints the integration consumes. No mutations."""
    raw: dict[str, Any] = {
        "router_info": await api.router_info(),
        "router_get_status": await api.router_get_status(),
        "connected_clients": await api.connected_clients(),
        "wifi_ifaces_get": await api.wifi_ifaces_get(),
    }
    if await api.tailscale_configured():
        raw["tailscale_get_config"] = await api._tailscale_get_config()  # noqa: SLF001
        raw["_tailscale_connection_state"] = (
            await api.tailscale_connection_state()
        ).name
    wireguard = await api.wireguard_client_list()
    if wireguard:
        raw["wireguard_client_list"] = wireguard
        raw["wireguard_client_state"] = await api.wireguard_client_state()
    return raw


def build_manifest(profile_id: str, clean: dict[str, Any]) -> dict[str, Any]:
    """Derive a profile manifest from the sanitised endpoint payloads."""
    info = clean["router_info"]
    clients = clean.get("connected_clients", {})
    tracked = sum(
        1
        for c in clients.values()
        if (c.get("alias") or "").strip() or (c.get("name") or "").strip()
    )
    has_tailscale = "tailscale_get_config" in clean
    connection_state = clean.get("_tailscale_connection_state", "DISCONNECTED")
    endpoints: dict[str, Any] = {"tailscale_configured": has_tailscale}
    if has_tailscale:
        endpoints["tailscale_connection_state"] = connection_state
    return {
        "id": profile_id,
        "model": str(info.get("model", "")).upper(),
        "firmware_version": info.get("firmware_version", ""),
        "factory_mac": info.get("mac", ""),
        "title": f"GL-iNet {str(info.get('model', '')).upper()}",
        "description": f"Captured and sanitised from a live {info.get('model')}.",
        "capabilities": {
            "has_wireguard": "wireguard_client_list" in clean,
            "has_tailscale": has_tailscale,
            "tailscale_connected": connection_state
            == TailscaleConnection.CONNECTED.name,
        },
        "endpoints": endpoints,
        "expected": {
            "connected_client_count": len(clients),
            "tracked_device_count": tracked,
            "unnamed_client_count": len(clients) - tracked,
            "wifi_iface_count": len(clean.get("wifi_ifaces_get", {})),
            "wireguard_client_count": len(clean.get("wireguard_client_list", [])),
            "wireguard_connection_count": len(clean.get("wireguard_client_list", [])),
        },
        "semantic": {
            "_note": "Fill in a few stable state values to assert against, e.g.",
            "cpu_temp": "",
            "load_avg1": "",
            "uptime_seconds": 0,
        },
    }


def write_profile(profile_id: str, clean: dict[str, Any], out: Path) -> None:
    """Write the sanitised endpoint JSONs and the derived manifest."""
    profile_dir = out / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    for name, data in clean.items():
        if name.startswith("_"):
            continue  # internal helper values (e.g. tailscale connection state)
        _dump(profile_dir / f"{name}.json", data)
    _dump(profile_dir / "profile.json", build_manifest(profile_id, clean))
    print(
        f"wrote {profile_dir} ({len([k for k in clean if not k.startswith('_')])} endpoints)"
    )


def _dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


async def capture(args: argparse.Namespace) -> None:
    """Connect, fetch, sanitise and write the profile."""
    api = GLinet(
        base_url=args.host + API_PATH,
        client=AiohttpClient(),
        sync=False,
    )
    await api.login(args.username, args.password)
    raw = await fetch_raw(api)

    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(raw["router_info"])
    clean = {
        name: (data if name.startswith("_") else sanitise(data, sanitiser))
        for name, data in raw.items()
    }
    write_profile(args.profile_id, clean, args.out)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.environ.get("GLINET_HOST", "http://192.168.8.1"),
        help="Router base URL (env: GLINET_HOST).",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("GLINET_USERNAME", "root"),
        help="Router username (env: GLINET_USERNAME).",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("GLINET_PASSWORD"),
        help="Router password (env: GLINET_PASSWORD).",
    )
    parser.add_argument(
        "--profile-id",
        required=True,
        help="Profile directory name, e.g. 'flint3' or 'mt6000_fw4_8'.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=FIXTURES,
        help="Fixtures root to write the profile into.",
    )
    args = parser.parse_args()
    if not args.password:
        parser.error("a password is required (--password or GLINET_PASSWORD)")
    return args


def main() -> None:
    """Entry point: parse args and run the capture."""
    asyncio.run(capture(_parse_args()))


if __name__ == "__main__":
    main()
