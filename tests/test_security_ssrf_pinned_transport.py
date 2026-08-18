"""T62: the address accepted by SSRF validation is the connected peer."""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import cast

import pytest

import arena.browser.fetch as browser_fetch
import arena.mcp.tool_net as tool_net
import arena.observability.webhooks as webhooks
import arena.security_http as http
import arena.security_ssrf as ssrf

PUBLIC = "93.184.216.34"
PRIVATE = "127.0.0.1"


def answer(address: str, port: int = 443):
    return [(2, 1, 6, "", (address, port))]


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("ftp://example.test/a", "URL scheme 'ftp' not allowed (only http/https)"),
        ("http:///a", "missing host"),
        ("http://localhost/", "internal/metadata hostname not allowed"),
        ("http://x.localhost/", "internal/metadata hostname not allowed"),
        ("http://x.localdomain/", "internal/metadata hostname not allowed"),
        ("http://x.internal/", "internal/metadata hostname not allowed"),
        ("http://x.local/", "internal/metadata hostname not allowed"),
        ("http://127.0.0.1/", "private/internal address not allowed"),
        ("http://99999999999999/", "malformed numeric address not allowed"),
        ("http://[/", "invalid URL"),
    ],
)
def test_public_addresses_rejects_static_bypasses_exactly(url, message):
    with pytest.raises(http.PublicUrlRejected) as caught:
        http._public_addresses(url)
    assert str(caught.value) == message


def test_public_literal_never_uses_dns(monkeypatch):
    monkeypatch.setattr(
        ssrf.socket,
        "getaddrinfo",
        lambda *_a, **_k: pytest.fail("numeric public address must not resolve"),
    )

    parsed, addresses = http._public_addresses("HTTP://8.8.8.8.:8080/a")

    assert parsed.scheme == "http"
    assert addresses == ("8.8.8.8",)


def test_public_addresses_normalizes_terminal_dot_before_dns(monkeypatch):
    seen = []

    def resolve(host, port, *, type):
        seen.append((host, port, type))
        return answer(PUBLIC, port)

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", resolve)

    http._public_addresses("https://Example.Test./path")

    assert seen == [("example.test", 443, ssrf.socket.SOCK_STREAM)]


def test_public_addresses_performs_one_authoritative_lookup(monkeypatch):
    calls = []

    def resolve(host, port, *, type):
        calls.append((host, port, type))
        return answer(PUBLIC, port)

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", resolve)

    parsed, addresses = http._public_addresses("https://example.test/path")

    assert parsed.hostname == "example.test"
    assert addresses == (PUBLIC,)
    assert calls == [("example.test", 443, ssrf.socket.SOCK_STREAM)]


def test_rebinding_to_private_address_is_rejected_at_connection_time(monkeypatch):
    calls = 0

    def resolve(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return answer(PUBLIC if calls == 1 else PRIVATE)

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", resolve)

    assert ssrf._validate_url("https://rebind.test/") is None
    with pytest.raises(http.PublicUrlRejected, match="private/internal"):
        http._public_addresses("https://rebind.test/")
    assert calls == 2


def test_http_connection_uses_pinned_ip_but_preserves_host(monkeypatch):
    connected = []
    sentinel = object()

    def create_connection(address, timeout, source_address):
        connected.append((address, timeout, source_address))
        return sentinel

    monkeypatch.setattr(ssrf.socket, "create_connection", create_connection)
    connection = http._PinnedHTTPConnection(
        "example.test",
        (PUBLIC,),
        port=8080,
        timeout=7,
        source_address=("192.0.2.1", 0),
    )

    connection.connect()

    assert connection.host == "example.test"
    assert connection.sock is sentinel
    assert connection.blocksize == 8192
    assert connected == [((PUBLIC, 8080), 7, ("192.0.2.1", 0))]


def test_connection_falls_back_across_validated_addresses(monkeypatch):
    calls = []
    sentinel = object()

    def create_connection(address, timeout, source_address):
        calls.append((address, timeout, source_address))
        if address[0] == PUBLIC:
            raise OSError("first peer unavailable")
        return sentinel

    monkeypatch.setattr(ssrf.socket, "create_connection", create_connection)
    connection = http._PinnedHTTPConnection(
        "example.test",
        (PUBLIC, "93.184.216.35", "93.184.216.36"),
        port=80,
        timeout=4,
    )

    connection.connect()

    assert connection.sock is sentinel
    assert calls == [
        ((PUBLIC, 80), 4, None),
        (("93.184.216.35", 80), 4, None),
    ]


def test_connection_fails_with_last_peer_error(monkeypatch):
    errors = iter((OSError("first"), OSError("last")))
    monkeypatch.setattr(
        ssrf.socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(next(errors)),
    )
    connection = http._PinnedHTTPConnection(
        "example.test", (PUBLIC, "93.184.216.35"), port=80
    )

    with pytest.raises(OSError, match="last"):
        connection.connect()
    with pytest.raises(OSError) as caught:
        http._connect_validated(
            (), port=80, timeout=1, source_address=None
        )
    assert str(caught.value) == "no validated peer addresses"


def test_https_connection_uses_original_host_for_sni(monkeypatch):
    connected = []
    wrapped = []
    raw_socket = object()
    tls_socket = object()

    def create_connection(address, timeout, source_address):
        connected.append((address, timeout, source_address))
        return raw_socket

    class Context:
        minimum_version = http.ssl.TLSVersion.TLSv1

        def wrap_socket(self, sock, *, server_hostname):
            wrapped.append((sock, server_hostname))
            return tls_socket

    monkeypatch.setattr(ssrf.socket, "create_connection", create_connection)
    connection = http._PinnedHTTPSConnection(
        "example.test",
        (PUBLIC,),
        port=8443,
        timeout=9,
        source_address=("2001:db8::1", 0),
        context=cast(http.ssl.SSLContext, Context()),
    )

    connection.connect()

    assert connection.sock is tls_socket
    assert connection.blocksize == 8192
    assert connected == [((PUBLIC, 8443), 9, ("2001:db8::1", 0))]
    assert wrapped == [(raw_socket, "example.test")]


@pytest.mark.parametrize(
    ("url", "expected_port"),
    [("http://example.test/", 80), ("https://example.test/", 443)],
)
def test_public_addresses_uses_scheme_default_port(monkeypatch, url, expected_port):
    seen = []

    def resolve(host, port, *, type):
        seen.append((host, port, type))
        return answer(PUBLIC, port)

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", resolve)

    http._public_addresses(url)

    assert seen == [("example.test", expected_port, ssrf.socket.SOCK_STREAM)]


def test_public_addresses_wraps_dns_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise ssrf.socket.gaierror("gone")

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", fail)

    with pytest.raises(urllib.error.URLError) as caught:
        http._public_addresses("https://missing.test/")
    assert str(caught.value.reason) == "cannot resolve public host 'missing.test'"


def test_public_addresses_requires_dns_answer(monkeypatch):
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *_a, **_k: [])

    with pytest.raises(urllib.error.URLError) as caught:
        http._public_addresses("https://missing.test/")
    assert str(caught.value.reason) == "cannot resolve public host 'missing.test'"


def test_public_addresses_checks_every_dns_answer(monkeypatch):
    monkeypatch.setattr(
        ssrf.socket,
        "getaddrinfo",
        lambda *_a, **_k: answer(PUBLIC) + answer("169.254.169.254"),
    )

    with pytest.raises(http.PublicUrlRejected) as caught:
        http._public_addresses("https://mixed.test/")
    assert str(caught.value) == "host resolves to a private/internal address"


def test_http_handler_pins_custom_port_and_revalidates_next_hop(monkeypatch):
    answers = iter((answer(PUBLIC, 8080), answer(PRIVATE, 8081)))
    monkeypatch.setattr(
        ssrf.socket, "getaddrinfo", lambda *_a, **_k: next(answers)
    )
    handler = http._PinnedHTTPHandler()
    monkeypatch.setattr(
        handler,
        "do_open",
        lambda factory, _request: factory("ignored", timeout=5),
    )

    first = cast(http._PinnedHTTPConnection, handler.http_open(urllib.request.Request("http://first.test:8080/a")))

    assert first.host == "first.test"
    assert first.port == 8080
    assert first._pinned_addresses == (PUBLIC,)
    with pytest.raises(http.PublicUrlRejected, match="private/internal"):
        handler.http_open(urllib.request.Request("http://redirect.test:8081/b"))


def test_https_handler_preserves_host_port_pin_and_context(monkeypatch):
    context = http.ssl.create_default_context()
    context.minimum_version = http.ssl.TLSVersion.MINIMUM_SUPPORTED
    handler = http._PinnedHTTPSHandler(context=context)
    assert context.minimum_version == http.ssl.TLSVersion.TLSv1_2
    request = urllib.request.Request("https://tls.example.test:9443/a")
    seen = []

    monkeypatch.setattr(
        http,
        "_public_addresses",
        lambda url: (
            seen.append(url)
            or (urllib.parse.urlparse(url), (PUBLIC,))
        ),
    )
    monkeypatch.setattr(
        handler,
        "do_open",
        lambda factory, _request: factory("ignored", timeout=6),
    )

    connection = cast(http._PinnedHTTPSConnection, handler.https_open(request))

    assert seen == ["https://tls.example.test:9443/a"]
    assert connection.host == "tls.example.test"
    assert connection.port == 9443
    assert connection._pinned_addresses == (PUBLIC,)
    assert connection._ssl_context is context


def test_https_handler_creates_default_tls_context():
    handler = http._PinnedHTTPSHandler()
    assert isinstance(handler._context, http.ssl.SSLContext)
    assert handler._context.minimum_version == http.ssl.TLSVersion.TLSv1_2


def test_open_public_url_disables_proxies_and_installs_pinned_handlers(monkeypatch):
    captured = []
    expected = object()

    class Opener:
        def open(self, request, *, timeout):
            captured.append((request, timeout))
            return expected

    def build_opener(*handlers):
        captured.extend(handlers)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    request = urllib.request.Request("https://example.test/")

    assert http.open_public_url(request, timeout=4) is expected
    assert isinstance(captured[0], urllib.request.ProxyHandler)
    assert getattr(captured[0], "proxies") == {}
    assert isinstance(captured[1], http._PinnedHTTPHandler)
    assert isinstance(captured[2], http._PinnedHTTPSHandler)
    assert captured[3] == (request, 4)


class _Response:
    status = 200
    headers = {"Content-Type": "text/plain"}

    def __init__(self, body: bytes = b"<title>T</title><main>body</main>") -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int | None = None) -> bytes:
        return self.body


def test_browser_fetch_surfaces_use_pinned_transport(monkeypatch):
    opened = []

    def open_pinned(request, *, timeout):
        opened.append((request.full_url, request.method, timeout))
        return _Response()

    monkeypatch.setattr(browser_fetch, "open_public_url", open_pinned)

    def validator(_url):
        return None

    browser_fetch.browser_search("query", 1, version="test")
    browser_fetch.browser_read(
        "https://example.test/read", version="test", validate_url=validator
    )
    browser_fetch.browser_dump(
        "https://example.test/dump", version="test", validate_url=validator
    )
    browser_fetch.browser_fetch(
        "https://example.test/fetch", version="test", validate_url=validator
    )
    browser_fetch.browser_head(
        "https://example.test/head", version="test", validate_url=validator
    )

    assert [item[0] for item in opened] == [
        "https://lite.duckduckgo.com/lite/?q=query",
        "https://example.test/read",
        "https://example.test/dump",
        "https://example.test/fetch",
        "https://example.test/head",
    ]
    assert opened[-1][1:] == ("HEAD", 15)


def test_mcp_net_http_uses_pinned_transport(monkeypatch):
    opened = []
    monkeypatch.setattr(tool_net, "_validate_url", lambda _url: None)
    monkeypatch.setattr(
        tool_net,
        "open_public_url",
        lambda request, *, timeout: opened.append((request, timeout)) or _Response(b"ok"),
    )

    result = tool_net._handle_net_http(
        {"url": "https://example.test/api", "method": "GET", "timeout": 3}
    )

    assert result["ok"] is True
    assert opened[0][0].full_url == "https://example.test/api"
    assert opened[0][1] == 3


def test_strict_webhook_uses_pinned_transport(monkeypatch):
    opened = []
    monkeypatch.setenv("ARENA_WEBHOOK_STRICT", "1")
    monkeypatch.setattr(ssrf, "_validate_url", lambda _url: None)
    monkeypatch.setattr(
        http,
        "open_public_url",
        lambda request, *, timeout: opened.append((request, timeout)) or _Response(),
    )

    webhooks._send_one("https://example.test/hook", b"{}")

    assert opened[0][0].full_url == "https://example.test/hook"
    assert opened[0][0].method == "POST"
    assert opened[0][1] == 5
