"""Guarded downloads of remote media into memory (stills, provider outputs).

Rules: https only, every hop's host must resolve to public addresses only (no SSRF into
the local stack), optional host allowlist, redirects followed manually (max 3, each hop
re-checked), declared and actual size capped, content type must match ``allowed_types``.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 3
_CHUNK = 64 * 1024

Resolver = Callable[[str], Iterable[str]]


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Downloaded:
    data: bytes
    content_type: str
    final_url: str


def resolve_host(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Exact host or a subdomain of an allowlisted suffix (``.example.com``)."""
    host = host.lower().rstrip(".")
    for entry in allowed_hosts:
        entry = entry.lower()
        if host == entry.lstrip(".") or (entry.startswith(".") and host.endswith(entry)):
            return True
    return False


def check_url(
    url: str, *, resolver: Resolver = resolve_host, allowed_hosts: Iterable[str] | None = None
) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DownloadError(f"only https URLs can be downloaded, got {parts.scheme or 'none'!r}")
    host = parts.hostname
    if not host:
        raise DownloadError("URL has no host")
    if allowed_hosts is not None and not host_allowed(host, allowed_hosts):
        raise DownloadError(f"host {host!r} is not on the allowlist")
    try:
        addresses = list(resolver(host))
    except OSError as exc:
        raise DownloadError(f"cannot resolve {host!r}: {exc}") from None
    if not addresses:
        raise DownloadError(f"cannot resolve {host!r}")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise DownloadError(f"host {host!r} resolves to a non-public address")
    return host


def _media_type(header: str | None) -> str:
    return (header or "").split(";", 1)[0].strip().lower()


def download(
    client: httpx.Client,
    url: str,
    *,
    allowed_types: tuple[str, ...],
    max_bytes: int,
    allowed_hosts: Iterable[str] | None = None,
    resolver: Resolver = resolve_host,
) -> Downloaded:
    """Fetch ``url`` fully into memory. ``allowed_types`` entries ending in '/' match a
    prefix (``"image/"``); others must match exactly."""
    allowlist = list(allowed_hosts) if allowed_hosts is not None else None
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        check_url(current, resolver=resolver, allowed_hosts=allowlist)
        try:
            with client.stream("GET", current, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadError("redirect without a location")
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise DownloadError(
                        f"HTTP {response.status_code} for {urlsplit(current).hostname}"
                    )
                content_type = _media_type(response.headers.get("content-type"))
                if not any(
                    content_type.startswith(t) if t.endswith("/") else content_type == t
                    for t in allowed_types
                ):
                    raise DownloadError(f"unexpected content type {content_type or 'none'!r}")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise DownloadError(f"file is larger than {max_bytes} bytes")
                buf = bytearray()
                for chunk in response.iter_bytes(_CHUNK):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise DownloadError(f"file is larger than {max_bytes} bytes")
                if not buf:
                    raise DownloadError("empty response body")
                return Downloaded(bytes(buf), content_type, current)
        except httpx.HTTPError as exc:
            raise DownloadError(f"download failed ({type(exc).__name__}: {exc})") from None
    raise DownloadError(f"more than {MAX_REDIRECTS} redirects")
