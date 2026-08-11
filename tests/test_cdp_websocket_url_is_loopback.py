"""A CDP debug endpoint may name a tab, not choose the destination.

`arena/browser/cdp_client/` asks the browser's HTTP debug port for a tab
list and connects to the `webSocketDebuggerUrl` it finds there. That URL
came out of a JSON body and was dialled unchecked.

Bug #56, verified by execution: a stand-in listening on the CDP port
answered

    {"type": "page", "webSocketDebuggerUrl":
     "ws://attacker.example:9999/devtools/page/STOLEN"}

and `get_websocket_url` returned it verbatim for `AsyncCDPBrowser.connect`
to open. A CDP socket can read every page, every cookie and every
keystroke in the browser, so where it points is not a detail.

The request is always to `http://127.0.0.1:<port>`, so the honest rule is
that the answer must describe that same port: `ws`/`wss`, a loopback
host, and the port we asked about. Anything else returns None, which
surfaces as the existing "Cannot connect to browser CDP on port N" --
the failure shape callers already handle.

Whether an attacker can control that reply is a fair question, and the
answer is "sometimes": any local process can bind a free port, and
`--remote-debugging-port` values are guessable. Cheap to close, so it is
closed.

Sabotage record (mandatory per AGENTS.md):
  1. `_loopback_ws_url` returning `raw` unconditionally
     -> test_a_foreign_host_is_rejected fails.
  2. dropping the port comparison
     -> test_a_different_port_is_rejected fails.
  3. dropping the scheme check
     -> test_non_websocket_schemes_are_rejected fails.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from arena.browser.cdp_client import tabs_http

# ---------------------------------------------------------------------------
# The predicate.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "ws://attacker.example:9222/devtools/page/X",
    "ws://192.168.1.5:9222/devtools/page/X",
    "ws://169.254.169.254:9222/x",
    "wss://evil.test:9222/x",
    "ws://127.0.0.1.evil.test:9222/x",
    "ws://localhost.evil.test:9222/x",
])
def test_a_foreign_host_is_rejected(url):
    assert tabs_http._loopback_ws_url(url, 9222) is None


@pytest.mark.parametrize("url", [
    "ws://127.0.0.1:1234/devtools/page/X",
    "ws://127.0.0.1:9223/devtools/page/X",
    "ws://localhost:80/x",
])
def test_a_different_port_is_rejected(url):
    """The reply must describe the port we asked about, not another one."""
    assert tabs_http._loopback_ws_url(url, 9222) is None


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:9222/x",
    "https://127.0.0.1:9222/x",
    "file:///etc/hostname",
    "javascript:alert(1)",
    "/devtools/page/X",
    "devtools/page/X",
])
def test_non_websocket_schemes_are_rejected(url):
    assert tabs_http._loopback_ws_url(url, 9222) is None


@pytest.mark.parametrize("value", [None, "", 0, [], {}, b"ws://127.0.0.1:9222/x"])
def test_non_string_values_are_rejected(value):
    """The field is whatever the JSON contained; it may not be a string."""
    assert tabs_http._loopback_ws_url(value, 9222) is None


@pytest.mark.parametrize("url", [
    "ws://127.0.0.1:9222/devtools/page/ABC",
    "ws://localhost:9222/devtools/page/ABC",
    "wss://127.0.0.1:9222/devtools/page/ABC",
])
def test_a_real_loopback_url_is_accepted(url):
    """A guard that blocks the normal case is a guard someone deletes."""
    assert tabs_http._loopback_ws_url(url, 9222) == url


# ---------------------------------------------------------------------------
# End to end through the HTTP lookup.
# ---------------------------------------------------------------------------

@pytest.fixture()
def cdp_stub():
    """A fake CDP debug endpoint that answers with a chosen URL."""
    servers = []

    def start(ws_url: str) -> int:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps([{
                    "type": "page", "id": "1", "title": "t",
                    "webSocketDebuggerUrl": ws_url,
                }]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        servers.append(server)
        return server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_get_websocket_url_refuses_a_hijacked_reply(cdp_stub):
    """The original repro."""
    port = cdp_stub("ws://attacker.example:9999/devtools/page/STOLEN")

    assert tabs_http.get_websocket_url(port, 0) is None, (
        "the tab list decided where the CDP client connects; that reply "
        "should only be able to name a tab on the port we asked"
    )


def test_get_websocket_url_accepts_a_genuine_reply():
    """A real browser names its own port; that must still work."""
    holder: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps([{
                "type": "page", "id": "1",
                "webSocketDebuggerUrl":
                    f"ws://127.0.0.1:{holder['port']}/devtools/page/ABC",
            }]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    holder["port"] = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        result = tabs_http.get_websocket_url(holder["port"], 0)
    finally:
        server.shutdown()
        server.server_close()

    assert result == f"ws://127.0.0.1:{holder['port']}/devtools/page/ABC"


def test_every_websocket_url_reader_is_guarded():
    """Three call sites read the field; all must go through the check."""
    import pathlib

    source = pathlib.Path(tabs_http.__file__).read_text(encoding="utf-8")
    readers = source.count('"webSocketDebuggerUrl"') + source.count(
        "'webSocketDebuggerUrl'")
    guarded = source.count("_loopback_ws_url(")

    # One occurrence is the filter in list comprehension, and one is the
    # helper's own definition -- so guarded calls must cover the readers
    # that actually return a value.
    assert guarded >= 3, (
        f"only {guarded} guarded call sites for {readers} readers of "
        "webSocketDebuggerUrl"
    )
