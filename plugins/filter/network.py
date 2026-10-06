"""Filters for network values that end up in published ingress configuration."""

from __future__ import annotations

import ipaddress
from typing import Any


def is_cidr(value: Any) -> bool:
    """True for an IPv4 or IPv6 network written as ``address/prefix``.

    Parsed with ``ipaddress`` in strict mode, so out-of-range octets, prefix
    lengths beyond the family's width, host bits under the prefix and anything
    without an explicit prefix are refused instead of reaching Traefik. The
    prefix must be a decimal length and the address unscoped, as Go requires.
    """

    if not isinstance(value, str) or value.count("/") != 1 or value != value.strip():
        return False
    address, prefix = value.split("/")
    # Go's net.ParseCIDR, which Traefik uses, takes neither a netmask in place
    # of the prefix length nor a scoped IPv6 address; ipaddress takes both.
    if not prefix.isascii() or not prefix.isdigit() or "%" in address:
        return False
    try:
        ipaddress.ip_network(value, strict=True)
    except ValueError:
        return False
    return True


class FilterModule:
    """Expose collection filters to Ansible."""

    def filters(self) -> dict[str, Any]:
        return {"is_cidr": is_cidr}
