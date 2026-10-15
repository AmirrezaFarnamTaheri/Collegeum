"""Outbound HTTP destination guard for independently discovered crawler URLs.

This is defence in depth, not a substitute for deployment egress isolation.
The address can change between DNS inspection and connect (DNS rebinding);
production runners should also firewall RFC1918, loopback, link-local and
metadata services at the network boundary. Mock transports skip live DNS.
"""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

_PRIVATE_SUFFIXES = (
    ".localhost", ".local", ".internal", ".test", ".invalid",
    ".example", ".home.arpa", ".onion",
)
_MAX_URL_LENGTH = 8192


class UnsafeDestination(ValueError):
    """URL cannot be used as an outbound crawler destination."""


def _public_address(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # inet_aton also recognizes IPv4 shorthand, octal and hexadecimal forms.
    # Those can resolve to 127.0.0.1 even when ipaddress.ip_address refuses.
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def validate_public_url(
    url: str,
    *,
    resolve_dns: bool = True,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    """Validate a public HTTP(S) destination, including all DNS A/AAAA answers.

    DNS is checked on each redirect hop. Do not use this with untrusted proxy
    settings; network egress restrictions remain essential.
    """
    if not isinstance(url, str) or len(url) > _MAX_URL_LENGTH or not url:
        raise UnsafeDestination("invalid URL length")
    if any(ord(char) < 33 or ord(char) == 127 for char in url):
        raise UnsafeDestination("invalid URL characters")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as exc:
        raise UnsafeDestination("malformed URL") from exc
    if (parts.scheme.lower() not in {"https", "http"} or not parts.netloc
            or not host or parts.username is not None or parts.password is not None):
        raise UnsafeDestination("non-public URL scheme or authority")
    if port == 0:
        raise UnsafeDestination("invalid outbound port")
    if (host in {"localhost", "localhost.localdomain"} or host.endswith(_PRIVATE_SUFFIXES)
            or "." not in host and ":" not in host):
        raise UnsafeDestination("private or ambiguous hostname")
    literal = _literal_address(host)
    if literal is not None:
        if not literal.is_global:
            raise UnsafeDestination("non-public IP address")
        return url
    if not resolve_dns:
        return url
    try:
        answers = resolver(host, port or (443 if parts.scheme.lower() == "https" else 80),
                           type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise UnsafeDestination("DNS lookup failed") from exc
    if not answers:
        raise UnsafeDestination("unresolved destination")
    for answer in answers:
        try:
            addr = answer[4][0]
        except (IndexError, TypeError, KeyError) as exc:
            raise UnsafeDestination("invalid DNS response") from exc
        if not _public_address(addr):
            raise UnsafeDestination("DNS address is not public")
    return url
