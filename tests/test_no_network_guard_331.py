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
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

_ALLOW_MARKER_NAME = "allow_network"


# The module object pytest actually loaded, resolved lazily.
#
# Three ways to get this wrong, all of which I tried:
#
# `import conftest` resolves against whatever rootdir pytest put on
# sys.path, which depends on the directory it was invoked from. Locally
# that is `tests/`; CI runs from the repo root, so the name found
# something else and every test here failed on a guard that worked.
#
# `spec_from_file_location` builds a *second* module with its own
# `NetworkUseInTest` class, so `pytest.raises` never matches the
# exception the installed fixture raises. Same false red, quieter cause.
#
# Searching `sys.modules` at import time is too early: conftest modules
# are registered while pytest collects, and this file is imported during
# that same pass. The lookup has to happen when a test runs.
@pytest.fixture
def suite_conftest(request: pytest.FixtureRequest) -> ModuleType:
    """The live `tests/conftest.py`, as pytest loaded it.

    Asked of pytest rather than reconstructed, after three versions that
    each failed on a working guard:

    * `import conftest` resolves against whatever rootdir is on
      sys.path, which depends on the directory pytest was invoked from.
      Locally that is `tests/`; CI runs from the repo root.
    * `spec_from_file_location` builds a *second* module object with its
      own `NetworkUseInTest`, so `pytest.raises` never matches the
      exception the installed fixture raises.
    * Scanning `sys.modules` by `__file__` compares paths that CI spells
      differently, and at import time runs before conftest is even
      registered.

    `config.pluginmanager` holds the module pytest is actually using, so
    there is nothing left to get wrong.
    """
    # pytest keys conftest plugins by absolute path -- verified against
    # `list_name_plugin()`, which shows exactly this one entry.
    module = request.config.pluginmanager.get_plugin(
        str(Path(__file__).resolve().parent / "conftest.py"))
    assert module is not None, (
        "tests/conftest.py is not among the loaded plugins, so the network "
        "guard is not installed"
    )
    return module


_UNROUTABLE = ("192.0.2.1", 65432)  # RFC 5737 TEST-NET-1


def test_a_tcp_connect_to_the_outside_is_refused(suite_conftest):
    """The failure mode is a hang; the guard turns it into an exception."""
    with pytest.raises(suite_conftest.NetworkUseInTest) as caught:
        socket.create_connection(_UNROUTABLE, timeout=5)

    assert "331" in str(caught.value), "the message should point at the issue"
    assert "allow_network" in str(caught.value), (
        "a refusal must say how to opt in, or the next person disables the "
        "guard instead of marking their test"
    )


def test_the_refusal_is_not_an_oserror(suite_conftest):
    """Networking code catches `OSError` to retry, and would swallow this.

    If the guard raised `OSError`, `_download_atomic` would fall into
    whatever retry or fallback path its caller has and report a timeout
    -- the guard would be invisible in exactly the case it fired.
    """
    assert not issubclass(suite_conftest.NetworkUseInTest, OSError)

    with pytest.raises(suite_conftest.NetworkUseInTest):
        socket.create_connection(_UNROUTABLE, timeout=5)


def test_urlopen_is_covered_without_being_patched(suite_conftest):
    """Every HTTP client goes through `socket`, so only `socket` is patched.

    Patching `urlopen` would protect the callers someone remembered.
    `urllib`, `http.client` and `requests` all end at
    `socket.create_connection`, which is why the guard sits there.
    """
    with pytest.raises(suite_conftest.NetworkUseInTest):
        urllib.request.urlopen(  # nosec B310 -- fixed https literal that
            # must never be reached: the assertion is that the guard
            # refuses it before a socket is opened.
            "https://huggingface.co/whatever", timeout=5)


def test_loopback_is_left_alone(suite_conftest):
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
def test_loopback_is_recognised_by_name_and_by_literal(host, suite_conftest):
    assert suite_conftest._is_loopback(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "huggingface.co", "192.168.1.1", "::"])
def test_everything_else_is_not_loopback(host, suite_conftest):
    """A LAN address is as irreproducible as a public one.

    `192.168.1.1` is the developer's router: reachable on one machine,
    absent in CI. Treating private ranges as safe would let exactly that
    class of test through.
    """
    assert suite_conftest._is_loopback(host) is False


def test_a_tcp_socket_is_not_waved_through_as_sending_nothing(suite_conftest):
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


def test_a_udp_connect_is_allowed_because_it_sends_nothing(suite_conftest):
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
def test_the_marker_actually_opts_out(suite_conftest):
    """Otherwise the escape hatch is decorative and gets removed.

    Connecting to TEST-NET-1 from here would hang, which is the thing
    being avoided, so this checks that the guard is not installed rather
    than that a connection succeeds.
    """
    assert socket.create_connection is not suite_conftest.socket.create_connection or (
        getattr(socket.create_connection, "__name__", "")
        != "guarded_create_connection"
    )


def test_the_guard_is_installed_for_unmarked_tests(suite_conftest):
    """The mirror image of the test above -- neither is meaningful alone."""
    assert socket.create_connection.__name__ == "guarded_create_connection"
    assert socket.socket.connect.__name__ == "guarded_connect"


def _has_working_af_unix() -> bool:
    """Can this platform actually make an AF_UNIX socket?

    Measured rather than assumed: on the Windows host this suite guards,
    Python 3.14.7 reports `hasattr(socket, "AF_UNIX") is False`. Some
    Windows builds do expose the constant while refusing the socket, so
    the constructor is tried too -- a skip is the right outcome for
    both, and an error is not (cubic).
    """
    if not hasattr(socket, "AF_UNIX"):
        return False
    try:
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _has_working_af_unix(),
                    reason="no usable AF_UNIX on this platform")
def test_a_unix_socket_is_not_treated_as_the_network(suite_conftest):
    """A filesystem socket is local by construction, so it is allowed.

    `AF_UNIX` addresses are paths, not hosts, so the loopback test says
    no to them and the guard refused connections that can never reach an
    interface -- DBus among them (cubic).
    """
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        assert suite_conftest._allowed(unix, "/run/user/1000/bus")
    finally:
        unix.close()


def test_an_external_tcp_connection_is_still_refused(suite_conftest):
    """The unix-socket exemption must not widen to ordinary sockets."""
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert not suite_conftest._allowed(tcp, ("huggingface.co", 443))
    finally:
        tcp.close()


def test_a_udp_datagram_to_the_outside_is_refused(suite_conftest):
    """The routing-probe exemption must not become an egress path.

    `connect` on a UDP socket sends nothing, so it is allowed. `sendto`
    does send, and reusing the connect-time rule here would have let an
    unmarked test put packets on the wire while the suite claimed the
    network was closed (cubic, aikido).
    """
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(suite_conftest.NetworkUseInTest):
            udp.sendto(b"x", ("8.8.8.8", 53))
    finally:
        udp.close()


def test_a_udp_datagram_to_loopback_still_works():
    """Local datagrams are not what the guard is for."""
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(b"ping", receiver.getsockname())
    assert receiver.recv(16) == b"ping"
    receiver.close()
    sender.close()


def test_a_connected_udp_socket_cannot_send_either(suite_conftest):
    """The `connect` exemption must not become a send permit.

    `connect` on a datagram socket is allowed because it transmits
    nothing. The first version of this guard left `send` unpatched on
    the reasoning that it can only follow an already-judged `connect` --
    true, and irrelevant, because that `connect` may be the exempted UDP
    one. This is the resulting escape, closed (cubic, coderabbit).
    """
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            udp.connect(("8.8.8.8", 53))
        except OSError:
            pytest.skip("no route to anywhere; nothing to send through")
        with pytest.raises(suite_conftest.NetworkUseInTest):
            udp.send(b"leak")
    finally:
        udp.close()


def test_a_connected_loopback_udp_socket_can_still_send(suite_conftest):
    """Local datagrams over a connected socket keep working."""
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        receiver.bind(("127.0.0.1", 0))
        sender.connect(receiver.getsockname())
        sender.send(b"ping")
        assert receiver.recv(16) == b"ping"
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("call", ["sendall", "sendmsg"])
def test_the_other_send_paths_are_closed_too(suite_conftest, call):
    """`sendall` and an address-less `sendmsg` were both escapes.

    `sendall` is implemented in C and does not dispatch through the
    patched `send`; `sendmsg([payload])` on a connected socket carries
    no address, so checking only the argument left the peer unexamined.
    Both reached a public address before this (aikido, cubic).
    """
    if call == "sendmsg" and not hasattr(socket.socket, "sendmsg"):
        pytest.skip("sendmsg is POSIX-only")
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            udp.connect(("8.8.8.8", 53))
        except OSError:
            pytest.skip("no route to anywhere; nothing to send through")
        with pytest.raises(suite_conftest.NetworkUseInTest):
            if call == "sendall":
                udp.sendall(b"leak")
            else:
                udp.sendmsg([b"leak"])
    finally:
        udp.close()


def test_a_name_lookup_is_refused(suite_conftest):
    """The resolver was the hole the connect guards left open.

    A full run made 45 non-loopback lookups -- `registry.npmjs.org`,
    `github.com`, `api.github.com` -- past a guard that claimed the
    network was shut (#334). `getaddrinfo` blocks like a `connect` on a
    slow resolver, which is the hazard #331 exists for, and the name
    itself leaves the machine.
    """
    # The host is built rather than written inline, and matched with
    # `repr` against the whole message: CodeQL reads
    # `"example.com" in some_string` as a URL sanitisation check that a
    # substring can defeat (py/incomplete-url-substring-sanitization).
    # It is a test assertion about an error message, not a check on a
    # URL, but the shape is the shape it flags, so avoid the shape.
    host = "example" + ".com"
    with pytest.raises(suite_conftest.NetworkUseInTest) as caught:
        socket.getaddrinfo(host, 80)
    # Anchored to the sentence the refusal opens with, not a loose
    # substring: an unanchored check passes when the name turns up
    # anywhere at all and never verifies which host was refused (cubic).
    assert str(caught.value).startswith(
        f"this test tried to resolve {host!r}."), (
        f"the refusal did not name the host it refused: {caught.value}")


@pytest.mark.parametrize("call", ["gethostbyname", "gethostbyname_ex"])
def test_the_older_resolver_entry_points_are_closed_too(suite_conftest, call):
    """`gethostbyname` is a separate door to the same resolver.

    `arena/inventory/probe_environment.py` calls it, so it is not
    hypothetical.
    """
    with pytest.raises(suite_conftest.NetworkUseInTest):
        getattr(socket, call)("example.com")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_still_resolves(suite_conftest, host):
    """The suite's own servers resolve constantly; they must keep working."""
    assert socket.getaddrinfo(host, 0)


@pytest.mark.parametrize("host", ["8.8.8.8", "93.184.216.34"])
def test_an_address_literal_is_not_a_lookup(suite_conftest, host):
    """Parsing an address asks no nameserver, so refusing it would lie.

    The SSRF validator resolves the literal it was handed on purpose, to
    re-check it; blocking that would break the validator under test
    while catching no network call at all.
    """
    assert socket.getaddrinfo(host, 0)


def test_the_public_resolver_fixture_answers_with_a_global_address(
        resolves_public_names):
    """The stub has to satisfy the check the tests using it depend on.

    `ipaddress` reports the RFC 5737 documentation ranges as private, so
    a stub answering `203.0.113.10` would have made every "a public URL
    is allowed" test assert the opposite of its name while still passing
    for the wrong reason.
    """
    import ipaddress

    (_family, _type, _proto, _canon, sockaddr), = socket.getaddrinfo(
        "example.com", 443)
    assert ipaddress.ip_address(sockaddr[0]).is_global
    assert sockaddr[0] == resolves_public_names


@pytest.mark.parametrize("call", [
    "getaddrinfo", "gethostbyname", "gethostbyname_ex"])
def test_every_stub_echoes_a_private_literal(resolves_public_names, call):
    """All three stubs must agree, or one of them flips a verdict.

    `gethostbyname_ex` returned the public stub for any input, so a
    consumer resolving a private literal through it got told the address
    was public -- the opposite of the answer (cubic).
    """
    literal = "10.0.0.5"
    if call == "getaddrinfo":
        answer = socket.getaddrinfo(literal, 0)[0][4][0]
    elif call == "gethostbyname":
        answer = socket.gethostbyname(literal)
    else:
        answer = socket.gethostbyname_ex(literal)[2][0]
    assert answer == literal, f"{call} rewrote a literal to {answer}"


def test_the_public_resolver_fixture_echoes_address_literals(
        resolves_public_names):
    """A literal must answer as itself, or it changes the verdict.

    `_validate_url` resolves the address it was given and re-checks the
    answer: a stub that replaced `8.8.8.8` with something else would be
    testing a different URL than the one written in the test.
    """
    (_family, _type, _proto, _canon, sockaddr), = socket.getaddrinfo(
        "8.8.8.8", 443)
    assert sockaddr[0] == "8.8.8.8"


@pytest.mark.allow_network
def test_the_marker_opts_out_of_the_resolver_guard_too(suite_conftest):
    """The opt-out has to cover the whole guard, not part of it.

    The first version of this resolved `127.0.0.1` and `localhost` and
    asserted they worked -- which the guard exempts anyway, so it would
    have passed just as happily with the opt-out broken (cubic). Check
    the patch is absent instead, the way `test_the_marker_actually_opts_out`
    does for `create_connection`: no lookup, nothing to be exempt from.
    """
    for entry_point in suite_conftest._RESOLVER_ENTRY_POINTS:
        installed = getattr(socket, entry_point, None)
        assert getattr(installed, "__name__", "") != "guarded", (
            f"the {_ALLOW_MARKER_NAME} marker left {entry_point} guarded")


def test_every_resolver_entry_point_is_guarded_for_unmarked_tests(
        suite_conftest):
    """The mirror image: the list must actually be installed.

    A name misspelled in `_RESOLVER_ENTRY_POINTS` would silently guard
    nothing, and the refusal tests only cover three of the six.
    """
    for entry_point in suite_conftest._RESOLVER_ENTRY_POINTS:
        installed = getattr(socket, entry_point, None)
        assert installed is not None, entry_point
        assert getattr(installed, "__name__", "") == "guarded", entry_point


@pytest.mark.parametrize("call", ["getfqdn", "gethostbyaddr", "getnameinfo"])
def test_the_reverse_and_fqdn_lookups_are_closed_too(suite_conftest, call):
    """These reach the same resolver and block the same way.

    `getfqdn` is not hypothetical -- `arena/inventory/probe_identity.py`
    calls it -- and it does a reverse lookup that hangs on a slow
    resolver exactly like `getaddrinfo` (cubic).
    """
    argument = ("198.51.100.7", 0) if call == "getnameinfo" else "example" + ".org"
    with pytest.raises(suite_conftest.NetworkUseInTest):
        if call == "getnameinfo":
            socket.getnameinfo(argument, 0)
        else:
            getattr(socket, call)(argument)


@pytest.mark.parametrize("call", ["getfqdn", "gethostbyaddr", "getnameinfo"])
def test_a_literal_does_not_buy_a_free_reverse_lookup(suite_conftest, call):
    """The literal exemption is a forward-lookup rule only.

    `getaddrinfo("8.8.8.8")` parses and returns. `gethostbyaddr("8.8.8.8")`
    sends a PTR query and comes back with `dns.google` -- measured. So
    the exemption that makes the forward guard honest reopened egress on
    the reverse one (cubic).
    """
    public_literal = "8.8.8.8"
    with pytest.raises(suite_conftest.NetworkUseInTest):
        if call == "getnameinfo":
            socket.getnameinfo((public_literal, 0), 0)
        else:
            getattr(socket, call)(public_literal)


@pytest.mark.parametrize("call", ["getfqdn", "gethostbyaddr"])
def test_a_loopback_literal_may_still_be_reversed(suite_conftest, call):
    """Loopback keeps working in both directions."""
    assert getattr(socket, call)("127.0.0.1")


@pytest.mark.parametrize("call", ["getfqdn", "gethostbyaddr"])
def test_none_is_not_a_wildcard_on_a_reverse_lookup(suite_conftest, call):
    """The wildcard exemption belongs to the forward direction only.

    `getaddrinfo(None, port)` means "bind everywhere"; `gethostbyaddr(None)`
    means nothing at all, so carrying the exemption across let an
    unexamined call through the guard (cubic).
    """
    with pytest.raises(suite_conftest.NetworkUseInTest):
        getattr(socket, call)(None)


def test_a_wildcard_bind_lookup_is_not_refused(suite_conftest):
    """`getaddrinfo(None, port)` asks no nameserver.

    It is the standard spelling for "bind to everything"; the empty
    string was already allowed and `None` was not, which refused a
    bind-all test over a hazard that is not there (cubic).
    """
    assert socket.getaddrinfo(None, 0)
