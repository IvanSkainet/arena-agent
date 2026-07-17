"""HTTP/socket probes for CDP test-launch diagnostics."""
from __future__ import annotations

import json
import socket
import urllib.request


def is_port_open(port: int, *, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def fetch_json(path: str, port: int, timeout: float = 3.0):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:  # nosec B310 -- loopback CDP endpoint
        return json.loads(response.read().decode())


def fetch_version_info(port: int):
    try:
        return fetch_json("/json/version", port)
    except Exception as e:
        return {"error": str(e)}


def attach_tabs_if_available(mode_result: dict, port: int) -> None:
    try:
        mode_result["tabs"] = fetch_json("/json/list", port)
    except Exception:
        pass
