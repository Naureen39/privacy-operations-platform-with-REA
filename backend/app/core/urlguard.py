"""Server side request forgery protection for user supplied website URLs.

A URL is accepted only when its host is on the allowlist and every address it resolves
to is safe. Loopback, link local (including cloud metadata), multicast, unspecified and
reserved addresses are always rejected. Private ranges are accepted only inside the
configured demo network. The resolved addresses are returned so the caller connects to
them directly (no second lookup, which would allow DNS rebinding). Callers must not
follow redirects without validating the target again.
"""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Sequence[str]]


class UrlRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedUrl:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


def system_resolver(host: str, port: int) -> Sequence[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _host_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    for entry in allowed_hosts:
        pattern = entry.lower().rstrip(".")
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _normalise(address: str) -> IPAddress:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def check_address(ip: IPAddress, allowed_networks: Sequence[str]) -> None:
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        raise UrlRejectedError(f"address {ip} is not permitted")
    for network in allowed_networks:
        net = ipaddress.ip_network(network, strict=False)
        if ip.version == net.version and ip in net:
            return
    if not ip.is_global:
        raise UrlRejectedError(f"address {ip} is in a private range outside the demo network")


def validate_observation_url(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    allowed_networks: Sequence[str] = (),
    allowed_ports: Sequence[int] = (80, 443),
    resolver: Resolver = system_resolver,
) -> ResolvedUrl:
    if len(url) > 2048:
        raise UrlRejectedError("URL is too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlRejectedError("URL is malformed") from exc
    if parts.scheme not in ("http", "https"):
        raise UrlRejectedError("only http and https URLs are accepted")
    if parts.username is not None or parts.password is not None:
        raise UrlRejectedError("credentials in the URL are not accepted")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlRejectedError("URL has no host")
    if not _host_allowed(host, allowed_hosts):
        raise UrlRejectedError("host is not on the allowlist")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in allowed_ports:
        raise UrlRejectedError("port is not permitted")

    try:
        raw = resolver(host, port)
    except OSError as exc:
        raise UrlRejectedError("host could not be resolved") from exc
    if not raw:
        raise UrlRejectedError("host did not resolve")
    addresses: list[str] = []
    for item in raw:
        try:
            ip = _normalise(item)
        except ValueError as exc:
            raise UrlRejectedError("host resolved to an invalid address") from exc
        check_address(ip, allowed_networks)
        addresses.append(str(ip))
    return ResolvedUrl(url=url, host=host, port=port, addresses=tuple(dict.fromkeys(addresses)))
