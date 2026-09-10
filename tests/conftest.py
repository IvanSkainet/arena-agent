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


@pytest.fixture(autouse=True)
def _no_outbound_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Refuse non-loopback connections for the duration of each test."""
    if request.node.get_closest_marker(_ALLOW_MARKER):
        return

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
