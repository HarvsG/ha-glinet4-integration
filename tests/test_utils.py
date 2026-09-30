"""Tests for the GL-iNet utility functions."""

from __future__ import annotations

import ssl

import aiohttp
import pytest

from custom_components.glinet.utils import adjust_mac, is_randomized_mac, is_ssl_error


def test_adjust_mac_increment() -> None:
    """Test incrementing a MAC address by one."""
    assert adjust_mac("00:1a:2b:3c:4d:5e", 1) == "00:1a:2b:3c:4d:5f"


def test_adjust_mac_decrement() -> None:
    """Test decrementing a MAC address by one."""
    assert adjust_mac("00:1a:2b:3c:4d:5f", -1) == "00:1a:2b:3c:4d:5e"


def test_adjust_mac_wraps_at_48_bits_up() -> None:
    """Test incrementing the highest MAC address wraps around to zero."""
    assert adjust_mac("ff:ff:ff:ff:ff:ff", 1) == "00:00:00:00:00:00"


def test_adjust_mac_wraps_at_48_bits_down() -> None:
    """Test decrementing the zero MAC address wraps around to all ff."""
    assert adjust_mac("00:00:00:00:00:00", -1) == "ff:ff:ff:ff:ff:ff"


def test_adjust_mac_dash_separator_and_case() -> None:
    """Test dashes and upper case input normalise to colon-lowercase output."""
    assert adjust_mac("00-1A-2B-3C-4D-5E", 1) == "00:1a:2b:3c:4d:5f"


def test_adjust_mac_no_separator() -> None:
    """Test a separator-less DHCP-style MAC address is handled."""
    assert adjust_mac("9483c4aabbcd", -1) == "94:83:c4:aa:bb:cc"


def test_is_ssl_error() -> None:
    """Test is_ssl_error detects SSL errors across exception causes."""
    assert not is_ssl_error(None)
    assert not is_ssl_error(ValueError("normal error"))
    assert not is_ssl_error(ConnectionError("refused"))

    ssl_err = ssl.SSLCertVerificationError("certificate verify failed")
    assert is_ssl_error(ssl_err)

    conn_cert_err = aiohttp.ClientConnectorCertificateError(None, ssl_err)  # type: ignore[arg-type]
    assert is_ssl_error(conn_cert_err)

    wrapped_err = KeyError("Parameter Exception:")
    wrapped_err.__cause__ = conn_cert_err
    assert is_ssl_error(wrapped_err)

    # Circular context safety
    err_a = ValueError("a")
    err_b = ValueError("b")
    err_a.__context__ = err_b
    err_b.__context__ = err_a
    assert not is_ssl_error(err_a)


@pytest.mark.parametrize(
    "mac",
    [
        "9A:99:5B:9C:81:37",  # randomized phone
        "96:B9:1F:99:EA:79",  # randomized phone
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
        "84:9E:56:B2:B2:57",  # real hardware OUI
        "1C:69:20:93:76:2B",  # real
        "00:06:78:B7:58:52",  # real
        "54:60:09:C0:70:B8",  # real
    ],
)
def test_real_macs(mac: str) -> None:
    """Universally-administered (real hardware) MACs are not randomized."""
    assert is_randomized_mac(mac) is False


@pytest.mark.parametrize("mac", ["", "xx", "g", None])
def test_malformed_mac_is_safe(mac: str | None) -> None:
    """Malformed/missing input never raises and defaults to not-randomized."""
    assert is_randomized_mac(mac) is False
