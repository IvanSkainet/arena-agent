"""DNS-pinned public HTTP transport used by SSRF-protected fetch surfaces."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, cast
from urllib.parse import ParseResult, urlparse

from arena.security_ssrf import (
    _BLOCKED_HOSTNAMES,
    _coerce_ip,
    _ip_is_blocked,
    _looks_numeric_host,
)


class PublicUrlRejected(ValueError):
    """The outbound URL did not satisfy the public-network contract."""


def _static_error(parsed: ParseResult, host: str) -> str | None:
    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"
    if not host:
        return "missing host"
    if (
        host in _BLOCKED_HOSTNAMES
        or host.endswith(".localhost")
        or host.endswith(".localdomain")
        or host.endswith(".internal")
        or host.endswith(".local")
    ):
        return "internal/metadata hostname not allowed"
    address = _coerce_ip(host)
    if address is not None and _ip_is_blocked(address):
        return "private/internal address not allowed"
    if address is None and _looks_numeric_host(host):
        return "malformed numeric address not allowed"
    return None


def _public_addresses(url: str) -> tuple[ParseResult, tuple[str, ...]]:
    """Validate and resolve once, returning only proven-public addresses."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().removesuffix(".").lower()
    except (TypeError, ValueError) as exc:
        raise PublicUrlRejected("invalid URL") from exc

    error = _static_error(parsed, host)
    if error:
        raise PublicUrlRejected(error)

    literal = _coerce_ip(host)
    if literal is not None:
        return parsed, (str(literal),)

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise urllib.error.URLError(f"cannot resolve public host {host!r}") from exc

    addresses: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in answers:
        address = ipaddress.ip_address(sockaddr[0])
        if _ip_is_blocked(address):
            raise PublicUrlRejected("host resolves to a private/internal address")
        rendered = str(address)
        if rendered not in addresses:
            addresses.append(rendered)
    if not addresses:
        raise urllib.error.URLError(f"cannot resolve public host {host!r}")
    return parsed, tuple(addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        pinned_address: str,
        port: int | None = None,
        *,
        timeout: Any = None,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
    ) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            source_address=source_address,
            blocksize=blocksize,
        )
        self._pinned_address = pinned_address
        self._source_address = source_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self._source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        pinned_address: str,
        port: int | None = None,
        *,
        timeout: Any = None,
        source_address: tuple[str, int] | None = None,
        context: ssl.SSLContext | None = None,
        blocksize: int = 8192,
    ) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            source_address=source_address,
            context=context,
            blocksize=blocksize,
        )
        self._pinned_address = pinned_address
        self._source_address = source_address
        self._ssl_context = context or ssl.create_default_context()

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self._source_address,
        )
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request):  # type: ignore[no-untyped-def]
        parsed, addresses = _public_addresses(req.full_url)
        host = cast(str, parsed.hostname)

        def factory(_host: str, **kwargs: Any) -> http.client.HTTPConnection:
            return _PinnedHTTPConnection(
                host, addresses[0], port=parsed.port, **kwargs
            )

        return self.do_open(factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        super().__init__(context=context)
        self._context = context or ssl.create_default_context()

    def https_open(self, req: urllib.request.Request):  # type: ignore[no-untyped-def]
        parsed, addresses = _public_addresses(req.full_url)
        host = cast(str, parsed.hostname)

        def factory(_host: str, **kwargs: Any) -> http.client.HTTPConnection:
            kwargs["context"] = self._context
            return _PinnedHTTPSConnection(
                host, addresses[0], port=parsed.port, **kwargs
            )

        return self.do_open(factory, req)


def open_public_url(
    url: str | urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None = None,
):  # type: ignore[no-untyped-def]
    """Open a public URL, pinning the validated IP for every redirect hop."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(context=context),
    )
    return opener.open(url, timeout=timeout)
