"""The network guard has to be checked like any other gate.

An autouse fixture is invisible when it works and equally invisible when
it stops working. `tests/conftest.py` is the only thing standing between
a stray `urlopen` and a lost Windows run (#331), so it gets tests of its
own: that it refuses the outside world, that it leaves loopback alone,
and that the opt-in marker actually opts out.

The last one matters most. A guard that cannot be turned off gets turned
off wholesale by the next person who needs a real connection.
"""
from __future__ import annotations

import socket
import sys
import urllib.request
from pathlib import Path

import pytest


# The module object pytest actually loaded, not a fresh one.
#
# `import conftest` is wrong: pytest puts a rootdir on sys.path for its
# own discovery, and which one depends on how it was invoked -- from the
# repo root, as CI does, the name resolves elsewhere. That turned the
# whole matrix red on a guard that was working.
#
# Re-importing the file by path is wrong too, and more quietly: it
# builds a *second* module with its own `NetworkUseInTest` class, so
# `pytest.raises` on it never matches the exception the installed
# fixture raises, and every test here fails while the guard works
# perfectly. Both mistakes were made on the way here.
#
# pytest registers the conftest it loaded under a plugin name, so ask
# for that one.
def _installed_conftest():
    plugin = Path(__file__).resolve().parent / "conftest.py"
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) and Path(module.__file__) == plugin:
            return module
    raise AssertionError(
        f"{plugin} is not loaded; the network guard is not installed")


suite_conftest = _installed_conftest()

_UNROUTABLE = ("192.0.2.1", 65432)  # RFC 5737 TEST-NET-1


def test_a_tcp_connect_to_the_outside_is_refused():
    """The failure mode is a hang; the guard turns it into an exception."""
    with pytest.raises(suite_conftest.NetworkUseInTest) as caught:
        socket.create_connection(_UNROUTABLE, timeout=5)

    assert "331" in str(caught.value), "the message should point at the issue"
    assert "allow_network" in str(caught.value), (
        "a refusal must say how to opt in, or the next person disables the "
        "guard instead of marking their test"
    )


def test_the_refusal_is_not_an_oserror():
    """Networking code catches `OSError` to retry, and would swallow this.

    If the guard raised `OSError`, `_download_atomic` would fall into
    whatever retry or fallback path its caller has and report a timeout
    -- the guard would be invisible in exactly the case it fired.
    """
    assert not issubclass(suite_conftest.NetworkUseInTest, OSError)

    with pytest.raises(suite_conftest.NetworkUseInTest):
        socket.create_connection(_UNROUTABLE, timeout=5)


def test_urlopen_is_covered_without_being_patched():
    """Every HTTP client goes through `socket`, so only `socket` is patched.

    Patching `urlopen` would protect the callers someone remembered.
    `urllib`, `http.client` and `requests` all end at
    `socket.create_connection`, which is why the guard sits there.
    """
    with pytest.raises(suite_conftest.NetworkUseInTest):
        urllib.request.urlopen("https://huggingface.co/whatever", timeout=5)


def test_loopback_is_left_alone():
    """~20 tests bind and dial 127.0.0.1; they are not the hazard."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket.create_connection(server.getsockname(), timeout=5)
        client.close()
    finally:
        server.close()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.53"])
def test_loopback_is_recognised_by_name_and_by_literal(host):
    assert suite_conftest._is_loopback(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "huggingface.co", "192.168.1.1", "::"])
def test_everything_else_is_not_loopback(host):
    """A LAN address is as irreproducible as a public one.

    `192.168.1.1` is the developer's router: reachable on one machine,
    absent in CI. Treating private ranges as safe would let exactly that
    class of test through.
    """
    assert suite_conftest._is_loopback(host) is False


def test_a_tcp_socket_is_not_waved_through_as_sending_nothing():
    """The UDP exemption must be about UDP, not about everything.

    `_sends_nothing` returning True for every socket disables the guard
    completely while every other test here still passes: refusals keep
    working through `create_connection`, which has its own check. Found
    by mutation -- the exemption needs a test that names the socket type
    it is exempting.
    """
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert suite_conftest._sends_nothing(udp) is True
        assert suite_conftest._sends_nothing(tcp) is False
        with pytest.raises(suite_conftest.NetworkUseInTest):
            tcp.connect(_UNROUTABLE)
    finally:
        tcp.close()
        udp.close()


def test_a_udp_connect_is_allowed_because_it_sends_nothing():
    """`arena/mobile/access_info.py` uses this to find the tailnet address.

    A UDP `connect` performs a routing-table lookup and transmits no
    packet, so it cannot hang -- the hazard the guard exists for. It
    returns in microseconds even for an unroutable target.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        assert sock.getsockname()[0]
    except OSError:
        pytest.skip("no route to anywhere; nothing to observe")
    finally:
        sock.close()


@pytest.mark.allow_network
def test_the_marker_actually_opts_out():
    """Otherwise the escape hatch is decorative and gets removed.

    Connecting to TEST-NET-1 from here would hang, which is the thing
    being avoided, so this checks that the guard is not installed rather
    than that a connection succeeds.
    """
    assert socket.create_connection is not suite_conftest.socket.create_connection or (
        getattr(socket.create_connection, "__name__", "")
        != "guarded_create_connection"
    )


def test_the_guard_is_installed_for_unmarked_tests():
    """The mirror image of the test above -- neither is meaningful alone."""
    assert socket.create_connection.__name__ == "guarded_create_connection"
    assert socket.socket.connect.__name__ == "guarded_connect"
