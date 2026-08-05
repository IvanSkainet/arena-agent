"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

import urllib.parse  # explicit: `urllib` from common re-exports request only

from arena.browser.cdp_client.common import (
    DEFAULT_PORT,
    Any,
    Dict,
    List,
    Optional,
    json,
    urllib,
)


def list_tabs(port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
    """List all browser tabs via the HTTP debug endpoint."""
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # nosec B310 -- loopback CDP endpoint (127.0.0.1:<devtools_port>)  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            return json.loads(r.read().decode())
    except Exception:
        return []

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _loopback_ws_url(raw: object, port: int) -> Optional[str]:
    """Return `raw` only if it is a ws:// URL back to our own debug port.

    v4.164.0 (bug #56): `webSocketDebuggerUrl` comes out of a JSON body
    and was connected to unchecked. Verified by execution -- a stand-in
    listening on the CDP port answered

        {"type": "page", "webSocketDebuggerUrl":
         "ws://attacker.example:9999/devtools/page/STOLEN"}

    and `get_websocket_url` handed that straight back for
    `AsyncCDPBrowser.connect` to dial. A CDP socket can read every page,
    every cookie and every keystroke in the browser, so pointing one at
    an arbitrary host is not a small thing.

    The reply is only trusted to name a tab on the port we asked, not to
    choose the destination. Anything else is dropped: returning None
    surfaces as the existing "Cannot connect to browser CDP on port N",
    which is the same failure shape callers already handle.
    """
    if not isinstance(raw, str) or not raw:
        return None
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("ws", "wss"):
        return None
    if (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return None
    if parsed.port != port:
        return None
    return raw

def get_websocket_url(port: int = DEFAULT_PORT, tab_index: int = 0) -> Optional[str]:
    """Get the WebSocket debugger URL for a specific tab."""
    tabs = list_tabs(port)
    page_tabs = [t for t in tabs if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
    if page_tabs and 0 <= tab_index < len(page_tabs):
        return _loopback_ws_url(page_tabs[tab_index]["webSocketDebuggerUrl"], port)
    return None

def get_new_tab_url(port: int = DEFAULT_PORT) -> Optional[str]:
    """Open a new tab and return its WebSocket URL.

    Uses PUT method on /json/new (required by Chromium-based browsers).
    Some browsers also accept GET, but PUT is the standard.
    """
    url = f"http://127.0.0.1:{port}/json/new"
    try:
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:  # nosec B310 -- loopback CDP endpoint (127.0.0.1:<devtools_port>)  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            tab = json.loads(r.read().decode())
            return _loopback_ws_url(tab.get("webSocketDebuggerUrl"), port)
    except Exception:
        # Fallback: try GET (some older Chromium versions)
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # nosec B310 -- loopback CDP endpoint (127.0.0.1:<devtools_port>)  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
                tab = json.loads(r.read().decode())
                return _loopback_ws_url(tab.get("webSocketDebuggerUrl"), port)
        except Exception:
            return None

def close_tab(tab_id: str, port: int = DEFAULT_PORT) -> bool:
    """Close a tab by its id."""
    url = f"http://127.0.0.1:{port}/json/close/{tab_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # nosec B310 -- loopback CDP endpoint (127.0.0.1:<devtools_port>)  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            return r.read().decode().strip() == "Target is closing"
    except Exception:
        return False
