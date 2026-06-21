"""Utility functions for GL-iNet routers."""


def is_randomized_mac(mac: str | None) -> bool:
    """Return True if a MAC address is locally administered (randomized).

    Modern phones use MAC randomization, setting the locally-administered bit
    (0x02 of the first octet). Such addresses change on each (re)connection, so
    a tracker keyed on them is short-lived clutter. Detection is purely from the
    address itself - no router support required. Malformed input is treated as
    not randomized.
    """
    try:
        first_octet = int(str(mac).replace(":", "").replace("-", "")[:2], 16)
    except (ValueError, IndexError):
        return False
    return bool(first_octet & 0x02)


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
