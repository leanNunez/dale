"""The client IP of a demo request (W8, DD36, ADR 0010; log D68-D71).

In demo mode the host sits behind Caddy on the same machine, so the peer is the proxy and the
visitor's address is in `X-Forwarded-For`. Caddy ignores the incoming header and sets one field
with the address it saw (or, from a `trusted_proxies` peer, appends that address), so the last
element of the last field is Caddy's own peer; anything before it is never read (log D71).
Only a peer at `127.0.0.1` or `::1` is the proxy; for any other peer the peer is the address and
the header is ignored. A value is an address only when `ipaddress` parses it whole: no port,
brackets or zone. The result is in canonical form, an IPv4-mapped address as IPv4, so one address
has one spelling; the limits key an IPv6 address by its /64 (slice 10, log D70). The guard puts
it in the request scope's state under `STATE_KEY`, and nothing else reads it; it is never logged
or stored in clear.
"""

import ipaddress
from typing import Final

STATE_KEY: Final = "client_ip"
PROXY: Final = frozenset({"127.0.0.1", "::1"})


def client_ip(peer: str | None, forwarded: list[str]) -> str | None:
    """The address limits count, or None when there is no usable one. `peer` is the host of
    the ASGI `client` and `forwarded` every `X-Forwarded-For` field in arrival order."""
    found = _address(peer)
    if found not in PROXY:
        return found
    return _address(forwarded[-1].rpartition(",")[2]) if forwarded else None


def _address(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        address = ipaddress.ip_address(text.strip(" \t"))
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id is not None:
            return None
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
    return str(address)
