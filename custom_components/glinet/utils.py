"""Utility functions for GL-iNet routers."""

from __future__ import annotations

import ssl

import aiohttp


def adjust_mac(mac: str, delta: int, sep: str = ":") -> str:
    """Increment a MAC address by 1.

    This is helpful because GL-iNet devices' LAN ports have a mac of factory_mac + 1
    but this is not found in the API
    :param mac: Original MAC address (e.g. "00:1A:2B:3C:4D:5E" or "00-1A-2B-3C-4D-5E").
    :param sep: Separator to use in the output (default is ':').
    :return: Incremented MAC address as a string.
    """
    # Remove common separators and convert to integer
    hex_str = mac.replace(sep, "").replace("-", "").lower()
    value = int(hex_str, 16)

    # Increment and wrap around at 48 bits
    value = (value + delta) & ((1 << 48) - 1)

    # Format back to hexadecimal, ensuring six bytes (12 hex digits)
    new_hex = f"{value:012x}"

    # Reinsert the separator every two hex digits
    return sep.join(new_hex[i : i + 2] for i in range(0, 12, 2)).lower()


def is_ssl_error(exc: BaseException | None) -> bool:
    """Check if an exception or its causes are SSL certificate verification errors."""
    curr = exc
    visited: set[int] = set()
    while curr is not None and id(curr) not in visited:
        if isinstance(
            curr, ssl.SSLCertVerificationError | aiohttp.ClientConnectorCertificateError
        ):
            return True
        visited.add(id(curr))
        curr = curr.__cause__ or curr.__context__
    return False
