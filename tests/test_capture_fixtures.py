"""Tests for the fixture-capture sanitiser.

These guard the property that matters: a captured profile committed to the repo
must never contain a real MAC, IP address or secret.
"""

from __future__ import annotations

import json

from scripts.capture_fixtures import Sanitiser, build_manifest, sanitise

REAL_CAPTURE = {
    "router_info": {
        "model": "mt6000",
        "firmware_version": "4.9.0",
        "mac": "94:83:c4:aa:bb:cc",
        "sn": "SN1234567890",
        "ddns": "abcdef.glddns.com",
        "board_info": {"model": "GL.iNet GL-MT6000", "hostname": "GL-MT6000-abc"},
    },
    "connected_clients": {
        "94:83:c4:11:22:33": {
            "mac": "94:83:c4:11:22:33",
            "name": "Shaun-iPhone",
            "alias": "",
            "ip": "192.168.8.42",
            "type": 1,
            "online": True,
        }
    },
    "wifi_ifaces_get": {
        "wifi5g": {"name": "wlan0", "ssid": "MyHomeNetwork", "encryption": "psk2"}
    },
}


def test_router_mac_is_seeded_first() -> None:
    """The router's own MAC always maps to the canonical ...:00:01."""
    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(REAL_CAPTURE["router_info"])
    clean = sanitise(REAL_CAPTURE["router_info"], sanitiser)
    assert clean["mac"] == "00:11:22:00:00:01"


def test_mac_mapping_is_stable_and_consistent() -> None:
    """A real MAC maps to the same fake MAC as both a dict key and a value."""
    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(REAL_CAPTURE["router_info"])
    clients = sanitise(REAL_CAPTURE["connected_clients"], sanitiser)
    # The client's MAC is remapped consistently as both the dict key and value.
    ((mac_key, info),) = clients.items()
    assert mac_key == info["mac"]
    assert mac_key == "00:11:22:00:00:02"  # second distinct MAC after the router


def test_no_real_pii_survives() -> None:
    """No real MAC, IP, serial, DDNS, client or SSID survives sanitisation."""
    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(REAL_CAPTURE["router_info"])
    blob = json.dumps(sanitise(REAL_CAPTURE, sanitiser))

    # MACs, IPs and secrets from the input must not appear in the output.
    for leaked in (
        "94:83:c4",
        "192.168.8.42",
        "SN1234567890",
        "abcdef.glddns.com",
        "Shaun-iPhone",
        "MyHomeNetwork",
    ):
        assert leaked not in blob


def test_categorical_values_are_preserved() -> None:
    """Model/encryption/type carry the model signal and must survive."""
    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(REAL_CAPTURE["router_info"])
    clean = sanitise(REAL_CAPTURE, sanitiser)
    # Model/encryption/type carry the model-difference signal and must survive.
    assert clean["router_info"]["model"] == "mt6000"
    assert clean["wifi_ifaces_get"]["wifi5g"]["encryption"] == "psk2"
    assert clean["connected_clients"]["00:11:22:00:00:02"]["type"] == 1


def test_build_manifest_derives_counts() -> None:
    """The derived manifest reads identity and counts from the payloads."""
    sanitiser = Sanitiser()
    sanitiser.seed_router_mac(REAL_CAPTURE["router_info"])
    clean = sanitise(REAL_CAPTURE, sanitiser)
    manifest = build_manifest("mt6000_test", clean)
    assert manifest["model"] == "MT6000"
    assert manifest["factory_mac"] == "00:11:22:00:00:01"
    assert manifest["expected"]["connected_client_count"] == 1
    assert manifest["expected"]["tracked_device_count"] == 1
    assert manifest["capabilities"]["has_wireguard"] is False
