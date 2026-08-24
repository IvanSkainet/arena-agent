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


def test_the_exemptions_still_exist():
    """A stale allowlist is worse than none: it silently permits a pattern
    nobody is choosing any more."""
    for name in DELIBERATE:
        assert (TESTS / name).exists(), f"{name} is gone; drop it from DELIBERATE"


def test_binding_to_port_zero_leaves_no_window():
    """The replacement genuinely holds the port, rather than just looking
    tidier: a second bind to the same port must be refused while the first
    server is alive."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a, **_kw):
            pass

    server = HTTPServer(("127.0.0.1", 0), _H)
    try:
        port = server.server_address[1]
        assert port > 0
        with pytest.raises(OSError):
            HTTPServer(("127.0.0.1", port), _H)
    finally:
        server.server_close()
