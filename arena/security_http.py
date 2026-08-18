"""DNS-pinned public HTTP transport used by SSRF-protected fetch surfaces."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import ParseResult, urlparse

from arena.security_ssrf import (
    _BLOCKED_HOSTNAMES,
    _coerce_ip,
    _ip_is_blocked,
    _looks_numeric_host,
)


class PublicUrlRejected(urllib.error.URLError, ValueError):
    """The outbound URL did not satisfy the public-network contract."""

    def __str__(self) -> str:
        return str(self.reason)


def _static_error(parsed: ParseResult, host: str) -> str | None:
    if parsed.scheme not in ("http", "https"):
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"
    if not host:
        return "missing host"
    if parsed.username is not None or parsed.password is not None:
        return "credentials in URL are not allowed"
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


def _public_addresses(url: str) -> tuple[ParseResult, str, tuple[str, ...]]:
    """Validate and resolve once, returning only proven-public addresses."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().removesuffix(".").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (TypeError, ValueError) as exc:
        raise PublicUrlRejected("invalid URL") from exc

    error = _static_error(parsed, host)
    if error:
        raise PublicUrlRejected(error)

    literal = _coerce_ip(host)
    if literal is not None:
        return parsed, host, (str(literal),)

    try:
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
    return parsed, host, tuple(addresses)


def _connect_validated(
    addresses: tuple[str, ...],
    *,
    port: int,
    timeout: Any,
    source_address: tuple[str, int] | None,
):  # type: ignore[no-untyped-def]
    """Try each already validated peer without performing another DNS lookup."""
    if not addresses:
        raise OSError("no validated peer addresses")
    for address in addresses[:-1]:
        try:
            return socket.create_connection(
                (address, port), timeout, source_address
            )
        except OSError:
            pass
    return socket.create_connection(
        (addresses[-1], port), timeout, source_address
    )


def _secure_client_context(context: ssl.SSLContext | None) -> ssl.SSLContext:
    """Return a certificate-verifying client context with TLS 1.2 minimum."""
    result = context or ssl.create_default_context()
    result.minimum_version = ssl.TLSVersion.TLSv1_2
    result.verify_mode = ssl.CERT_REQUIRED
    result.check_hostname = True
    return result


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        pinned_addresses: tuple[str, ...],
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
        self._pinned_addresses = pinned_addresses
        self._source_address = source_address

    def connect(self) -> None:
        self.sock = _connect_validated(
            self._pinned_addresses,
            port=self.port,
            timeout=self.timeout,
            source_address=self._source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        pinned_addresses: tuple[str, ...],
        port: int | None = None,
        *,
        timeout: Any = None,
        source_address: tuple[str, int] | None = None,
        context: ssl.SSLContext | None = None,
        check_hostname: bool | None = None,
        blocksize: int = 8192,
    ) -> None:
        # Python 3.10's urllib HTTPSHandler forwards ``check_hostname``;
        # newer runtimes removed it from HTTPSConnection. Accept the legacy
        # keyword but keep the public transport fail-closed regardless.
        del check_hostname
        secure_context = _secure_client_context(context)
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            source_address=source_address,
            context=secure_context,
            blocksize=blocksize,
        )
        self._pinned_addresses = pinned_addresses
        self._source_address = source_address
        self._ssl_context = secure_context

    def connect(self) -> None:
        sock = _connect_validated(
            self._pinned_addresses,
            port=self.port,
            timeout=self.timeout,
            source_address=self._source_address,
        )
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request):  # type: ignore[no-untyped-def]
        parsed, host, addresses = _public_addresses(req.full_url)
        def factory(_host: str, **kwargs: Any) -> http.client.HTTPConnection:
            return _PinnedHTTPConnection(
                host, addresses, port=parsed.port, **kwargs
            )

        return self.do_open(factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        secure_context = _secure_client_context(context)
        super().__init__(context=secure_context)
        self._context = secure_context

    def https_open(self, req: urllib.request.Request):  # type: ignore[no-untyped-def]
        parsed, host, addresses = _public_addresses(req.full_url)
        def factory(_host: str, **kwargs: Any) -> http.client.HTTPConnection:
            kwargs["context"] = self._context
            return _PinnedHTTPSConnection(
                host, addresses, port=parsed.port, **kwargs
            )

        return self.do_open(factory, req)


class _PublicHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            scheme = urlparse(newurl).scheme.lower()
        except (TypeError, ValueError) as exc:
            raise PublicUrlRejected("invalid redirect URL") from exc
        if scheme not in ("http", "https"):
            raise PublicUrlRejected("redirect scheme not allowed (only http/https)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_public_url(
    url: str | urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None = None,
):  # type: ignore[no-untyped-def]
    """Open a public URL, pinning the validated IP for every redirect hop."""
    initial_url = url.full_url if isinstance(url, urllib.request.Request) else url
    try:
        initial_scheme = urlparse(initial_url).scheme.lower()
    except (TypeError, ValueError) as exc:
        raise PublicUrlRejected("invalid URL") from exc
    if initial_scheme not in ("http", "https"):
        raise PublicUrlRejected("URL scheme not allowed (only http/https)")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(context=context),
        _PublicHTTPRedirectHandler(),
    )
    return opener.open(url, timeout=timeout)
