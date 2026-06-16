"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

def list_tabs(port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
    """List all browser tabs via the HTTP debug endpoint."""
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return []

def get_websocket_url(port: int = DEFAULT_PORT, tab_index: int = 0) -> Optional[str]:
    """Get the WebSocket debugger URL for a specific tab."""
    tabs = list_tabs(port)
    page_tabs = [t for t in tabs if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
    if page_tabs and 0 <= tab_index < len(page_tabs):
        return page_tabs[tab_index]["webSocketDebuggerUrl"]
    return None

def get_new_tab_url(port: int = DEFAULT_PORT) -> Optional[str]:
    """Open a new tab and return its WebSocket URL.

    Uses PUT method on /json/new (required by Chromium-based browsers).
    Some browsers also accept GET, but PUT is the standard.
    """
    url = f"http://127.0.0.1:{port}/json/new"
    try:
        req = urllib.request.Request(url, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            tab = json.loads(r.read().decode())
            return tab.get("webSocketDebuggerUrl")
    except Exception:
        # Fallback: try GET (some older Chromium versions)
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                tab = json.loads(r.read().decode())
                return tab.get("webSocketDebuggerUrl")
        except Exception:
            return None

def close_tab(tab_id: str, port: int = DEFAULT_PORT) -> bool:
    """Close a tab by its id."""
    url = f"http://127.0.0.1:{port}/json/close/{tab_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read().decode().strip() == "Target is closing"
    except Exception:
        return False
