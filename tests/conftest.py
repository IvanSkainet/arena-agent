"""Suite-wide guard: no test reaches the outside network.

Written after a whisper model download inside the suite hung a full local
Windows run (#331). The failure mode is worth stating precisely, because
it is not "one flaky test":

`pytest-timeout` uses `SIGALRM` where it exists and a timer thread where
it does not. Windows has no `SIGALRM`, so the fallback is a thread that
calls `os._exit(1)` -- it cannot raise into the stuck test, so it takes
down the interpreter. One socket blocked on a TLS read therefore ends
the entire run, mid-suite, with `RUN_FINISHED` still written to the log.

A truncated run then reads as a *clean* one: the pre-merge gate compares
failure ids against a baseline, and a run that stopped after 10% of the
suite reports fewer failures than the baseline, not more. Zero failures
against thirty looks like an improvement. That is the real damage --
losing the run is recoverable, being lied to about it is not.

So the network is closed by default and opened per test, rather than
each test being trusted to mock its own downloads. `socket.socket` is
patched at the one chokepoint every higher-level client goes through
(`urllib`, `http.client`, `requests`), which is also why this cannot be
done by patching `urlopen`: patching the library a test happens to use
only protects the paths someone remembered.

Loopback stays open. Roughly twenty tests bind or connect to 127.0.0.1
-- stub servers, the bridge, the fuzz gate -- and they are not what went
wrong here. Blocking them would be a much larger change sold as a
safety fix, and the ones that matter would get marked `allow_network`
to make the suite pass again, which is how a guard becomes decoration.

Tests that genuinely need the outside world declare it:

    @pytest.mark.allow_network
    def test_something_that_really_downloads(): ...

There are none today. The marker exists so that adding one is a visible,
reviewable act instead of a silent `urlopen`.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest

_ALLOW_MARKER = "allow_network"

# Loopback only. Not "private ranges": a test that reaches 192.168.1.1
# is talking to the developer's router, which is exactly as
# irreproducible as talking to huggingface.co.
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", ""})


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{_ALLOW_MARKER}: test may open sockets to hosts other than loopback",
    )


class NetworkUseInTest(RuntimeError):
    """Raised instead of letting a test reach the network.

    A subclass of `RuntimeError` rather than of `OSError`: a great deal
    of networking code catches `OSError` to fall back or retry, and this
    must not be swallowed into a retry loop and reported as a timeout.
    """


def _is_loopback(host: object) -> bool:
    """Is this address the local machine, by literal or by name?"""
    if not isinstance(host, str):
        return False
    name = host.strip("[]").lower()
    if name in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        # A hostname that is not an IP literal. Resolving it here would
        # be a DNS query -- a network call made by the thing meant to
        # prevent network calls -- so it is refused unresolved.
        return False


def _needs_no_resolver(host: object) -> bool:
    """Is this a lookup in name only, settled without a nameserver?

    Two spellings qualify. An address literal parses and returns. And
    `None` -- `getaddrinfo(None, port)` is the standard wildcard-bind
    spelling, equivalent to `""`, which was already allowed; glibc
    answers it from the local address without asking anyone, so
    refusing it would trip a bind-all test over a hazard that is not
    there (cubic).
    """
    return host is None or _is_address_literal(host)


def _is_address_literal(host: object) -> bool:
    """Is this already an address, needing no resolver to understand?

    `getaddrinfo("8.8.8.8", None)` parses the string and returns; it asks
    no nameserver, blocks on nothing and sends nothing. Refusing it would
    make the guard lie about what it caught -- and it would break the
    SSRF validator's literal path, which resolves the literal it was
    handed on purpose.
    """
    if not isinstance(host, str):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _sends_nothing(sock: socket.socket) -> bool:
    """Is `connect` on this socket a local operation?

    `connect` on a UDP socket transmits no packets: it asks the routing
    table which local address would be used to reach the target and
    stores it. `arena/mobile/access_info.py` relies on exactly that to
    discover the tailnet interface, and it returns in microseconds even
    when the target is unroutable -- measured, not assumed.

    So it cannot hang, which is the hazard this guard exists for, and
    blocking it would force a production module to be rewritten around
    a test fixture. TCP still goes through the guard.
    """
    return sock.type == socket.SOCK_DGRAM


def _is_unix_socket(sock: socket.socket) -> bool:
    """Is this a filesystem socket, which cannot leave the machine?

    An `AF_UNIX` address is a path, not a host, so `_is_loopback` says no
    to it and the guard would refuse a connection that is local by
    construction -- DBus, for one, which `arena/browser/cdp/handlers.py`
    talks to. Nothing sent over one reaches a network interface, so the
    hazard this guard exists for does not apply (cubic).
    """
    return getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object())


def _allowed(sock: socket.socket, address: object) -> bool:
    """May this socket connect to this address?"""
    host = address[0] if isinstance(address, tuple) and address else address
    return _is_unix_socket(sock) or _sends_nothing(sock) or _is_loopback(host)


def _refuse(address: object) -> NetworkUseInTest:
    host = address[0] if isinstance(address, tuple) and address else address
    return NetworkUseInTest(
        f"this test tried to connect to {host!r}. The suite runs with the "
        f"network closed: a real download inside the tests once hung a "
        f"whole Windows run, and on Windows pytest-timeout can only end "
        f"that by killing the interpreter, so the run was lost and the "
        f"truncated log still looked clean (#331).\n"
        f"Mock the client, point it at 127.0.0.1, or -- if the test "
        f"genuinely needs the outside world -- mark it "
        f"@pytest.mark.{_ALLOW_MARKER}."
    )


def _destination(args: tuple) -> object | None:
    """The address argument of a send call: last, and sometimes absent."""
    return args[-1] if args and isinstance(args[-1], (tuple, str, bytes)) else None


def _may_send_to(sock: socket.socket, target: object) -> bool:
    """May this socket put a datagram on the wire for this address?

    Explicitly not `_allowed`: that function waves every UDP socket
    through, because a UDP *connect* transmits nothing. A `sendto` does
    transmit, so reusing the connect-time rule here would reproduce the
    hole this guard exists to close.
    """
    host = target[0] if isinstance(target, tuple) and target else target
    return _is_unix_socket(sock) or _is_loopback(host)


def _install_connect_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse the calls that open a connection."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address, *args, **kwargs):
        if not _allowed(self, address):
            raise _refuse(address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        if not _allowed(self, address):
            raise _refuse(address)
        return real_connect_ex(self, address, *args, **kwargs)

    # `connect`/`connect_ex` and not `socket.socket.__init__`: creating a
    # socket is harmless and several tests do it to find a free port.
    # The connection attempt is the thing that can block for minutes.
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    # `create_connection` resolves the name itself and calls the real
    # `connect` on a socket object, so it needs its own guard: the DNS
    # lookup happens before any patched method is reached and can hang
    # on its own.
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        if not _is_loopback(address[0] if isinstance(address, tuple) else address):
            raise _refuse(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


def _refuse_connected_datagram(sock: socket.socket) -> None:
    """Refuse a `send` on a datagram socket connected to the outside.

    Only datagram sockets need this: a TCP `send` cannot outrun the
    handshake its `connect` already passed. `getpeername` raises when the
    socket is not connected, which is not this guard's business.
    """
    if sock.type != socket.SOCK_DGRAM:
        return
    try:
        peer = sock.getpeername()
    except OSError:
        return
    if not _may_send_to(sock, peer):
        raise _refuse(peer)


def _refuse_explicit_or_connected(sock: socket.socket, target: object) -> None:
    """Judge the address given, or the connected peer when none is.

    A send call either names its destination or inherits it from an
    earlier `connect`. Only the first was checked, so the datagram
    variants that omit the address -- `sendmsg([payload])` on a
    connected socket -- passed unexamined (cubic, aikido).
    """
    if target is None:
        _refuse_connected_datagram(sock)
        return
    if not _may_send_to(sock, target):
        raise _refuse(target)


def _install_send_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse the calls that carry their own destination.

    The UDP exemption in `_allowed` is about `connect`, which transmits
    nothing. Sending is a different act: a test could connect a datagram
    socket under that exemption and then put real packets on the wire
    (cubic, aikido).

    `send` is guarded too, and the first version of this was wrong to
    skip it: the reasoning was that `send` can only follow a `connect`
    that was already judged, which is true and irrelevant, because the
    `connect` it follows may be the UDP one that `_sends_nothing` waved
    through. `sock.connect(("8.8.8.8", 53))` then `sock.send(...)`
    reached the public peer -- the exact egress this guard claims to
    close (cubic, coderabbit). Its destination is the connected peer,
    read back with `getpeername()`.

    `sendmsg` is POSIX-only. Reading the attribute unconditionally took
    the whole Windows matrix down with an AttributeError inside the
    fixture, so each entry point is patched only where it exists.
    """
    real_send = socket.socket.send
    real_sendall = socket.socket.sendall
    real_sendto = socket.socket.sendto
    real_sendmsg = getattr(socket.socket, "sendmsg", None)

    def guarded_send(self, *args, **kwargs):
        _refuse_connected_datagram(self)
        return real_send(self, *args, **kwargs)

    def guarded_sendall(self, *args, **kwargs):
        # `sendall` is implemented in C and does not dispatch through the
        # patched `send`, so it needed its own guard (aikido).
        _refuse_connected_datagram(self)
        return real_sendall(self, *args, **kwargs)

    def guarded_sendto(self, *args, **kwargs):
        _refuse_explicit_or_connected(self, _destination(args))
        return real_sendto(self, *args, **kwargs)

    def guarded_sendmsg(self, *args, **kwargs):
        # `sock.sendmsg([payload])` on a connected socket carries no
        # address, so checking only the argument let the connected peer
        # through unexamined (cubic, aikido).
        _refuse_explicit_or_connected(self, _destination(args))
        return real_sendmsg(self, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "send", guarded_send)
    monkeypatch.setattr(socket.socket, "sendall", guarded_sendall)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    if real_sendmsg is not None:
        monkeypatch.setattr(socket.socket, "sendmsg", guarded_sendmsg)


def _refuse_resolution(host: object) -> NetworkUseInTest:
    """The refusal a name lookup gets, worded for a name lookup."""
    return NetworkUseInTest(
        f"this test tried to resolve {host!r}. The suite runs with the "
        f"network closed, and a name lookup is a network call: on a host "
        f"with a slow or broken resolver it blocks exactly like a "
        f"`connect`, and on Windows pytest-timeout can only end that by "
        f"killing the interpreter, so the run is lost and the truncated "
        f"log still looks clean (#331, #334).\n"
        f"Resolution is also an egress channel in its own right -- the "
        f"name being looked up is data leaving the machine.\n"
        f"Patch the resolver in the test (`socket.getaddrinfo`), use an "
        f"address literal, or -- if the test genuinely needs the outside "
        f"world -- mark it `@pytest.mark.{_ALLOW_MARKER}`."
    )


# What `getfqdn()` with no argument is asking about: the local machine's
# own name, resolved through a reverse lookup that talks to the same
# resolver as everything else here.
_THIS_MACHINE = "<this machine>"


# Every way to reach the resolver, not just the three obvious ones.
# `getfqdn` and `gethostbyaddr` do reverse lookups and `getnameinfo`
# resolves both directions; all three block on a slow resolver exactly
# like `getaddrinfo`, and `getfqdn` is used in production
# (`arena/inventory/probe_identity.py:21`,
# `arena/inventory/probe_environment.py`), so a test exercising that
# code path could still hang or leak a query (cubic).
#
# `gethostname` is deliberately absent: it reads a local name out of the
# kernel and asks no nameserver.
_FORWARD_RESOLVERS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex")

# The reverse direction, where the literal exemption does not hold. On a
# forward lookup an address literal parses and returns without asking
# anyone. On a reverse lookup the literal IS the query: measured,
# `socket.gethostbyaddr("8.8.8.8")` returns `dns.google` -- a PTR query
# that went out past the guard (cubic). So these take the loopback rule
# with no exemption.
_REVERSE_RESOLVERS = ("getfqdn", "gethostbyaddr", "getnameinfo")

_RESOLVER_ENTRY_POINTS = _FORWARD_RESOLVERS + _REVERSE_RESOLVERS


def _guarded_resolver(real_resolver: Any, *, literals_are_local: bool) -> Any:
    """Wrap one resolver entry point in the loopback policy.

    `literals_are_local` is the difference between the two directions:
    true for a forward lookup, where an address literal is parsed
    locally, and false for a reverse one, where the literal is precisely
    what gets asked about.
    """
    def guarded(*args, **kwargs):
        # `getfqdn()` takes no argument and means "this machine", which
        # is a local question -- but it answers it with a reverse lookup,
        # so it still has to be refused. Defaulting the absent host to
        # the empty string would exempt it (`""` is in
        # `_LOOPBACK_HOSTNAMES`), so the no-argument call is named
        # explicitly instead. Reading it as a required parameter broke
        # two inventory collectors with a TypeError.
        host = args[0] if args else kwargs.get(
            "host", kwargs.get("name", _THIS_MACHINE))
        # `getnameinfo` takes a sockaddr tuple, not a bare host.
        if isinstance(host, tuple) and host:
            host = host[0]
        # `None` is the wildcard-bind spelling for a *forward* lookup and
        # means nothing on a reverse one, so the exemption does not
        # travel with it (cubic). The reverse entry points reject None
        # themselves, but a guard should not be the thing relying on
        # that.
        local = _is_loopback(host) or (
            literals_are_local and _needs_no_resolver(host))
        if not local:
            raise _refuse_resolution(host)
        return real_resolver(*args, **kwargs)

    return guarded


def _install_resolver_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse the calls that turn a name into an address.

    The connect guards close the socket calls but not the lookup that
    precedes them (cubic, aikido, independently). A measured full run
    made 45 non-loopback lookups, `registry.npmjs.org`, `github.com` and
    `api.github.com` among them -- real queries to a real resolver on
    every run, reaching the network the guard above claims to have shut.

    Address literals still pass: `getaddrinfo("8.8.8.8", ...)` parses a
    string and asks no nameserver, so refusing it would name a hazard
    that is not there. A *name* is refused unresolved -- deciding whether
    a name is local requires the very lookup being guarded -- except
    "localhost", which RFC 6761 reserves to loopback, the same exemption
    `_is_loopback` already makes.
    """
    for entry_point in _RESOLVER_ENTRY_POINTS:
        real = getattr(socket, entry_point, None)
        if real is not None:
            monkeypatch.setattr(socket, entry_point, _guarded_resolver(
                real, literals_are_local=entry_point in _FORWARD_RESOLVERS))


# The address every stubbed lookup answers with. It has to satisfy
# `ipaddress.is_global`, because that is what the SSRF validator checks,
# and the RFC 5737 documentation ranges do not: Python reports
# `203.0.113.10` as `is_private`, so a stub using one would have made
# every "public URL is allowed" test assert the opposite of its name.
# This is the address `example.com` published for years -- recognisable,
# and nothing in the suite ever connects to it, since the connect guard
# is still in force.
_PUBLIC_STUB_IP = "93.184.216.34"


def _stub_answer(host: object) -> str:
    """What the stub resolves `host` to.

    An address literal answers as itself: `_validate_url` resolves the
    literal it was handed and re-checks the result, so echoing a
    different address would silently change the verdict under the test.
    One function for all three stubs, because `gethostbyname_ex` did not
    do this and would have flipped a verdict for a literal (cubic).
    """
    return host if _is_address_literal(host) else _PUBLIC_STUB_IP


@pytest.fixture
def resolves_public_names(monkeypatch: pytest.MonkeyPatch):
    """Answer every name lookup with one fixed public address.

    Twenty-one tests assert that a *public* URL passes the SSRF
    validator, and the validator settles that by resolving the host and
    checking the addresses (`arena/security_ssrf.py`,
    `arena/security_http.py`). With a real resolver those tests were
    quietly asking the developer's DNS what `example.com` and
    `api.github.com` resolve to -- so their verdict depended on the
    network, and on a machine behind a captive portal that answers
    everything with a private address, they would have failed for a
    reason that has nothing to do with the code (#334).

    Returning a fixed documentation address makes the assertion mean what
    it says: given a host that resolves publicly, the validator allows
    it. Tests that need a *private* answer patch the resolver themselves;
    this fixture is for the ordinary case.
    """
    def resolve(host, port=None, *args, **kwargs):
        address = _stub_answer(host)
        socktype = kwargs.get("type", args[1] if len(args) > 1 else 0)
        return [(socket.AF_INET, socktype or socket.SOCK_STREAM, 6, "",
                 (address, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "gethostbyname", _stub_answer)
    monkeypatch.setattr(
        socket, "gethostbyname_ex",
        lambda host: (host, [], [_stub_answer(host)]))
    return _PUBLIC_STUB_IP


# What a LAN lookup answers with. A real private address, because the
# tests that want one are about LAN behaviour: answering them with the
# public stub would have them assert against an address that is not on
# any LAN (cubic).
_LAN_STUB_IP = "192.168.7.20"


@pytest.fixture
def resolves_this_machine(monkeypatch: pytest.MonkeyPatch):
    """Answer the machine's own reverse lookups without going out.

    `socket.getfqdn()` asks a local question -- what am I called -- but
    answers it with a reverse lookup through the same resolver, so the
    guard refuses it. Two inventory collectors do exactly that on every
    run. Stub the answer rather than exempt `getfqdn`: the lookup is
    still a lookup, and a test that wants it should say so.
    """
    monkeypatch.setattr(socket, "getfqdn", lambda *_a, **_k: "test-host.local")
    monkeypatch.setattr(
        socket, "gethostbyaddr",
        lambda *_a, **_k: ("test-host.local", [], ["127.0.0.1"]))
    return "test-host.local"


@pytest.fixture
def resolves_the_local_hostname(monkeypatch: pytest.MonkeyPatch):
    """Resolve this machine's own name to a fixed private address.

    `arena/mobile/access_info.py` enumerates LAN addresses by resolving
    `socket.gethostname()`, so a test about LAN URLs needs that lookup to
    answer -- and to answer with something that is actually a LAN
    address. Only the local hostname is stubbed; everything else stays
    refused.
    """
    local_names = {socket.gethostname(), socket.gethostname().lower()}
    real_getaddrinfo = socket.getaddrinfo

    def resolve(host, port=None, *args, **kwargs):
        if host in local_names:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     (_LAN_STUB_IP, port or 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return _LAN_STUB_IP


@pytest.fixture(autouse=True)
def _no_outbound_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Refuse non-loopback networking for the duration of each test."""
    if request.node.get_closest_marker(_ALLOW_MARKER):
        return
    _install_connect_guards(monkeypatch)
    _install_send_guards(monkeypatch)
    _install_resolver_guards(monkeypatch)
