"""Client for the Interactive Input Helper.

Used by the bridge to route mouse/keyboard input through the helper
process running in the user's interactive session.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from arena.jsonshape import loads_object

_DEFAULT_PORT = 19222


def _helper_url() -> str:
    port = int(os.environ.get("ARENA_INPUT_HELPER_PORT", str(_DEFAULT_PORT)))
    return f"http://127.0.0.1:{port}"


def _helper_token() -> str:
    return os.environ.get("ARENA_INPUT_HELPER_TOKEN", "")


def _call(path: str, body: dict[str, Any] | None = None, *, method: str = "POST", timeout: int = 10) -> dict[str, Any]:
    """Call the helper server. Raises on connection errors."""
    url = f"{_helper_url()}{path}"
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    token = _helper_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- loopback-only helper; nosemgrep: dynamic-urllib-use-detected -- URL is fixed to 127.0.0.1 loopback with only the port variable
        return loads_object(resp.read().decode("utf-8", "replace"))


def is_available() -> bool:
    """Check if the helper is reachable."""
    try:
        r = _call("/health", method="GET", timeout=2)
        return bool(r.get("ok"))
    except Exception:
        return False


def health() -> dict[str, Any]:
    """Get helper health/status."""
    try:
        return _call("/health", method="GET", timeout=3)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def click(x: int, y: int, *, button: str = "left", double: bool = False) -> dict[str, Any]:
    return _call("/click", {"x": x, "y": y, "button": button, "double": double})


def move(x: int, y: int) -> dict[str, Any]:
    return _call("/move", {"x": x, "y": y})


def type_text(text: str, *, delay_ms: int = 5) -> dict[str, Any]:
    return _call("/type", {"text": text, "delay_ms": delay_ms})


def key(name: str, *, modifiers: list[str] | None = None) -> dict[str, Any]:
    return _call("/key", {"name": name, "modifiers": modifiers or []})


def launch(path: str, *, args: list[str] | None = None) -> dict[str, Any]:
    return _call("/launch", {"path": path, "args": args or []})


def send_chat_command(command: str, *, hwnd: int | None = None, open_key: str = "/") -> dict[str, Any]:
    body: dict[str, Any] = {"command": command, "open_key": open_key}
    if hwnd is not None:
        body["hwnd"] = hwnd
    return _call("/send_chat_command", body, timeout=15)


__all__ = ["click", "health", "is_available", "key", "launch", "move", "send_chat_command", "type_text"]
