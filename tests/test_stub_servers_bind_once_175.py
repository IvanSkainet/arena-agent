"""#175: test stub servers must bind their port once and never release it.

The pattern this forbids is:

    s = socket.socket(...); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                       # <-- port belongs to nobody here
    server = HTTPServer(("127.0.0.1", port), Handler)

Measured, the port is unowned for ~25us per stub start. That is small, but
it is a window for nothing: `HTTPServer(("127.0.0.1", 0), ...)` gets the
same result with no window at all, because the kernel holds the port for
the whole life of the server.

The window is worse on Windows than on Linux. `HTTPServer` sets
`SO_REUSEADDR`, and on Windows that permits a second bind to a port that
is still being listened on -- verified on the Windows host, where the
second bind succeeded. Two stubs can therefore land on one port with no
error at all, the second quietly taking connections. On Linux the same
bind is refused with errno 98.

Scope note, recorded so the next reader does not "fix" the exceptions:
three call sites bind-and-close deliberately and are NOT defects.

* `test_agentctl_breaker.py` needs a port guaranteed to be *dead*, so
  releasing it is the point.
* `test_bridge_stops_on_sigterm.py` hands a port number to a subprocess,
  which cannot inherit a bound socket.
* `test_tunnels_probe.py` keeps its socket and calls `listen()` on it, so
  it never had the window in the first place.

This gate is not what fixed the flake that prompted #175 -- that was a
latency inversion in `test_best_picks_fastest_from_client_vantage`, see
`test_agentctl_bridge.py`. Tightening the pattern is worth doing on its
own, and claiming otherwise would leave the real cause looking solved.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

# Files that bind-then-close on purpose, with the reason each is exempt.
DELIBERATE = {
    "test_agentctl_breaker.py": "needs a guaranteed-dead port",
    "test_bridge_stops_on_sigterm.py": "passes a port to a subprocess",
}

# A port number read off a socket that is then closed. Matching the release
# itself, rather than the rebind that follows, is deliberate: the first
# version of this gate looked for `<name> = HTTPServer(` after the close and
# missed `self.server = HTTPServer(`, because `\w+` does not span a dotted
# attribute. Caught by sabotage -- the gate passed while the pattern was
# back in the tree. The release is the defect; what happens next is detail.
PICK_CLOSE_REBIND = re.compile(
    r"getsockname\(\)\[1\][^\n]*\n(?:[^\n]*\n){0,3}?\s*[\w.]+\.close\(\)",
    re.MULTILINE,
)


def _test_files() -> list[Path]:
    # This file quotes the forbidden pattern in its own docstring, so it
    # must not scan itself.
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != Path(__file__).name)


@pytest.mark.parametrize("path", _test_files(), ids=lambda p: p.name)
def test_no_stub_server_picks_a_port_then_rebinds_it(path: Path):
    source = path.read_text(encoding="utf-8")
    match = PICK_CLOSE_REBIND.search(source)
    if match is None:
        return
    reason = DELIBERATE.get(path.name)
    assert reason is not None, (
        f"{path.name} picks a port, closes the socket and rebinds it. "
        f"Use HTTPServer((\"127.0.0.1\", 0), Handler) and read "
        f"server.server_address[1] instead (#175). If the release is "
        f"deliberate, add it to DELIBERATE with the reason."
    )


@pytest.mark.parametrize("name", sorted(DELIBERATE), ids=sorted(DELIBERATE))
def test_each_exemption_is_still_needed(name: str):
    """A stale allowlist is worse than none: it silently permits a pattern
    nobody is choosing any more.

    Asserting only that the file still exists does not do that -- an
    exemption whose file was cleaned up but whose entry stayed behind
    would pass, which is precisely the case the docstring claims to
    prevent. Raised in review of PR #176 and confirmed: both entries were
    passing on existence alone. The entry has to be revoked the moment the
    file stops needing it.
    """
    path = TESTS / name
    assert path.exists(), f"{name} is gone; drop it from DELIBERATE"
    source = path.read_text(encoding="utf-8")
    assert PICK_CLOSE_REBIND.search(source) is not None, (
        f"{name} no longer picks-and-releases a port, so its DELIBERATE "
        f"exemption ({DELIBERATE[name]}) is stale -- remove it."
    )


def test_binding_to_port_zero_yields_distinct_live_ports():
    """The replacement genuinely allocates, rather than just looking tidier.

    Deliberately *not* asserting that a second bind to the same port is
    refused. It is on Linux (`OSError` errno 98), but on Windows
    `SO_REUSEADDR` -- which `HTTPServer` sets by default -- lets a second
    bind take a port that is still being listened on, and it succeeds.
    Verified on the Windows host: `SECOND BIND SUCCEEDED`.

    That platform split is the substance, not a footnote: on Windows the
    pick-close-rebind window is worse than on Linux, because nothing
    complains when two stubs end up on one port -- the second simply
    starts stealing connections. An earlier version of this test encoded
    the Linux behaviour as universal and failed on the Windows host.

    What holds everywhere is that port 0 hands out distinct live ports,
    which is all the replacement pattern needs to promise.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a, **_kw):
            pass

    first = HTTPServer(("127.0.0.1", 0), _H)
    second = HTTPServer(("127.0.0.1", 0), _H)
    try:
        p1 = first.server_address[1]
        p2 = second.server_address[1]
        assert p1 > 0 and p2 > 0
        assert p1 != p2
    finally:
        first.server_close()
        second.server_close()


def test_the_gate_actually_rejects_the_forbidden_pattern(tmp_path, monkeypatch):
    """A scanner nobody has seen fail is a scanner nobody should trust.

    The first version of this gate matched `<name> = HTTPServer(` after the
    close, and `\\w+` does not span `self.server` -- so it passed while the
    forbidden pattern was sitting in the tree. That was found by sabotage,
    not by review, and this test is what makes the failure mode permanent
    rather than a story in a commit message.
    """
    offender = tmp_path / "test_offender_stub.py"
    offender.write_text(
        "import socket\n"
        "from http.server import HTTPServer\n"
        "def start(handler):\n"
        "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        '    s.bind(("127.0.0.1", 0))\n'
        "    self_port = s.getsockname()[1]\n"
        "    s.close()\n"
        '    return HTTPServer(("127.0.0.1", self_port), handler)\n',
        encoding="utf-8",
    )
    assert PICK_CLOSE_REBIND.search(offender.read_text(encoding="utf-8")) is not None

    # ...and the dotted-attribute form that the first regex missed.
    dotted = tmp_path / "test_offender_attr.py"
    dotted.write_text(
        "import socket\n"
        "from http.server import HTTPServer\n"
        "class S:\n"
        "    def start(self, handler):\n"
        "        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        '        self._sock.bind(("127.0.0.1", 0))\n'
        "        self.port = self._sock.getsockname()[1]\n"
        # A dotted receiver on the close, too: `\w+` does not span
        # `self._sock`, and narrowing the character class there let a real
        # sabotage through unnoticed while this test still passed.
        "        self._sock.close()\n"
        '        self.server = HTTPServer(("127.0.0.1", self.port), handler)\n',
        encoding="utf-8",
    )
    assert PICK_CLOSE_REBIND.search(dotted.read_text(encoding="utf-8")) is not None

    # The gate must fail for such a file when it is not exempt.
    monkeypatch.setattr("tests.test_stub_servers_bind_once_175.TESTS", tmp_path)
    with pytest.raises(AssertionError, match="picks a port"):
        test_no_stub_server_picks_a_port_then_rebinds_it(offender)


def test_the_replacement_pattern_is_not_flagged():
    """The gate must not fire on the fix it is asking for."""
    good = (
        "from http.server import HTTPServer\n"
        "def start(handler):\n"
        '    server = HTTPServer(("127.0.0.1", 0), handler)\n'
        "    return server, server.server_address[1]\n"
    )
    assert PICK_CLOSE_REBIND.search(good) is None
