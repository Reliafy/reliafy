"""The client's IP address, for rate limits and the daily visitor hash.

Every caller that keys anything on the client address uses :func:`client_ip`.

How the address is chosen
-------------------------
Each proxy in front of the app appends the address of the peer that connected
to it to ``X-Forwarded-For``. Anything to the left of what our own proxies
wrote came from the client and can say anything, so the header is read from
the RIGHT, never the left.

On Cloud Run, Google's front end appends exactly one entry: the address that
opened the connection to it. For a request sent straight to the ``run.app``
host (the SSE stream, upload links) that is the visitor. For a request that
comes through Firebase Hosting, Hosting forwards the visitor's address in the
header it sends on, and the front end then appends the address Hosting
connected from. Internal addresses (private, shared, loopback, link-local),
which only the infrastructure between the client and the app appends, are
skipped, as is anything in ``TRUSTED_PROXY_CIDRS``. The first remaining
entry from the right is the client.

If Hosting's own egress address turns out to be the right-most public entry
on proxied requests, list Hosting's ranges in ``TRUSTED_PROXY_CIDRS`` so the
next entry left (the visitor, as Hosting recorded it) is used instead.

``TRUST_X_FORWARDED_FOR=false`` ignores the header entirely and uses the
socket peer, for deployments reachable without a proxy in front.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from backend import config


@lru_cache(maxsize=8)
def _trusted_networks(cidrs: tuple[str, ...]):
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _parse(entry: str):
    entry = entry.strip().strip('"')
    if entry.startswith("[") and "]" in entry:  # "[v6]:port"
        entry = entry[1:entry.index("]")]
    elif entry.count(":") == 1:  # "v4:port"
        entry = entry.split(":", 1)[0]
    try:
        return ipaddress.ip_address(entry)
    except ValueError:
        return None


# Addresses only infrastructure appends: private, shared (carrier-grade NAT),
# loopback, link-local and unique-local ranges.
_INTERNAL = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
    "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
))


def _is_proxy_hop(addr, nets) -> bool:
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in (*_INTERNAL, *nets))


def from_forwarded_for(header: str, peer: str = "") -> str:
    """The client address from an ``X-Forwarded-For`` value (see the module
    docstring); ``peer`` when the header holds nothing usable."""
    entries = [e for e in (header or "").split(",") if e.strip()]
    if not entries:
        return peer
    nets = _trusted_networks(tuple(config.TRUSTED_PROXY_CIDRS))
    for raw in reversed(entries):
        addr = _parse(raw)
        if addr is None:
            # Not an address: whatever wrote it is untrusted from here left.
            return raw.strip()[:64]
        if not _is_proxy_hop(addr, nets):
            return str(addr)
    # Every entry is a proxy hop (an internal call): the left-most one.
    first = _parse(entries[0])
    return str(first) if first is not None else peer


def client_ip(request) -> str:
    """The client's address for ``request``. Only ever hashed, never stored."""
    peer = request.client.host if request.client else ""
    if not config.TRUST_X_FORWARDED_FOR:
        return peer
    return from_forwarded_for(request.headers.get("x-forwarded-for", ""), peer)
