"""External MCP server client (v4.94.0).

The bridge has long been an MCP *server* (it exposes its own tools) and the
marketplace could *register* external servers in ``mcp/mcp.json`` and probe
them one-shot (``tools/list``). What was missing was an MCP *client* that
keeps a server alive and actually CALLS its tools (``tools/call``) so the
agent can use external MCP servers (Desktop-Commander, ScreenPilot, ...)
through the bridge.

This module provides:

* ``McpStdioClient`` — a persistent stdio JSON-RPC connection to one MCP
  server. Requests are matched to responses by ``id``; server notifications
  (no ``id``) are skipped. Synchronous, thread-safe per client.
* ``McpClientManager`` — lazily starts/caches clients by server name from
  ``mcp/mcp.json`` (``mcpServers``), so repeated tool calls reuse one
  process instead of spawning ``npx`` every time.

Security: only an allowlist of interpreter/launcher commands may be spawned
(same list the marketplace ``test`` command uses) so a tampered config cannot
turn the client into an arbitrary command runner.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

# Commands the client is allowed to spawn. Mirrors the marketplace `test`
# allowlist so a tampered mcp.json cannot run an arbitrary binary. Full paths
# are permitted as long as their basename (sans .exe/.cmd/.bat) is allowed --
# this lets a git-venv server register its own venv interpreter
# (e.g. .../venv/Scripts/python.exe) while still blocking arbitrary binaries.
ALLOWED_COMMANDS = ("npx", "uvx", "uv", "python", "python3", "node")


def _command_allowed(command: str) -> bool:
    if command in ALLOWED_COMMANDS:
        return True
    base = os.path.basename(command).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base in ALLOWED_COMMANDS

_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_INFO = {"name": "arena-bridge", "version": "1.0"}


class McpError(Exception):
    """Raised when an MCP server cannot be started or speaks an error."""


class McpStdioClient:
    """A persistent stdio JSON-RPC connection to a single MCP server."""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | None = None):
        if not _command_allowed(command):
            raise McpError(
                f"refusing to spawn unknown command {command!r} "
                f"(allowed: {', '.join(ALLOWED_COMMANDS)} or a full path to one)")
        self.command = command
        self.args = list(args or [])
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.server_info: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self, timeout: float = 60) -> dict[str, Any]:
        """Spawn the server and run the initialize handshake."""
        if self.alive():
            return self.server_info
        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
                env=self.env, cwd=self.cwd,
            )
        except FileNotFoundError as e:
            raise McpError(
                f"command not found: {self.command} "
                f"(install it / check npx|uvx|python is on PATH)") from e
        resp = self.request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": _CLIENT_INFO,
        }, timeout=timeout)
        self.server_info = resp.get("result", {})
        self._notify("notifications/initialized")
        return self.server_info

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        self._tools = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # -- JSON-RPC ----------------------------------------------------------
    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.alive():
            raise McpError("server is not running")
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = 120) -> dict[str, Any]:
        """Send a request and block until the matching response arrives.

        Server-initiated notifications (no ``id``) are skipped. Returns the
        full JSON-RPC response object (``result`` or ``error``)."""
        with self._lock:
            if not self.alive():
                raise McpError("server is not running")
            self._id += 1
            rid = self._id
            msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                msg["params"] = params
            assert self.proc and self.proc.stdin and self.proc.stdout
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise McpError(f"server pipe broken: {e}") from e
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self.proc.stdout.readline()
                if line == "":  # EOF: server closed stdout (died)
                    raise McpError("server closed the connection (it likely crashed)")
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if resp.get("id") == rid:
                    return resp
                # otherwise it is a notification or a stale id -- skip
            raise McpError(f"MCP '{method}' timed out after {timeout}s")

    # -- MCP conveniences --------------------------------------------------
    def list_tools(self, timeout: float = 30, refresh: bool = False) -> list[dict[str, Any]]:
        if self._tools is not None and not refresh:
            return self._tools
        resp = self.request("tools/list", {}, timeout=timeout)
        if "error" in resp:
            raise McpError(f"tools/list error: {resp['error']}")
        self._tools = resp.get("result", {}).get("tools", [])
        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None,
                  timeout: float = 180) -> dict[str, Any]:
        resp = self.request("tools/call", {"name": name, "arguments": arguments or {}},
                            timeout=timeout)
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        result = resp.get("result", {})
        return {
            "ok": not result.get("isError", False),
            "content": result.get("content", []),
            "structured": result.get("structuredContent"),
            "isError": result.get("isError", False),
        }


class McpClientManager:
    """Lazily starts/caches MCP clients keyed by server name (mcp.json)."""

    def __init__(self, config_path: Path | str | None = None):
        if config_path is None:
            root = Path(os.environ.get("ARENA_AGENT_HOME",
                                       str(Path.home() / "arena-bridge"))).expanduser()
            config_path = root / "mcp" / "mcp.json"
        self.config_path = Path(config_path)
        self._clients: dict[str, McpStdioClient] = {}
        self._lock = threading.Lock()

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"mcpServers": {}}
        return {"mcpServers": {}}

    def servers(self) -> dict[str, dict[str, Any]]:
        """Return the configured servers (name -> config)."""
        return self._load_config().get("mcpServers", {})

    def get_client(self, name: str) -> McpStdioClient:
        with self._lock:
            client = self._clients.get(name)
            if client is not None and client.alive():
                return client
            srv = self.servers().get(name)
            if not srv:
                raise McpError(
                    f"MCP server '{name}' is not registered in {self.config_path}. "
                    f"Install it first (marketplace install / mcp.json).")
            client = McpStdioClient(
                srv.get("command", ""), srv.get("args", []),
                srv.get("env", {}), srv.get("cwd"))
            client.start()
            self._clients[name] = client
            return client

    def list_tools(self, name: str, refresh: bool = False) -> list[dict[str, Any]]:
        return self.get_client(name).list_tools(refresh=refresh)

    def call_tool(self, name: str, tool: str,
                  arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.get_client(name).call_tool(tool, arguments)

    def status(self, name: str) -> dict[str, Any]:
        client = self._clients.get(name)
        return {"registered": name in self.servers(),
                "running": bool(client and client.alive())}

    def stop(self, name: str) -> None:
        with self._lock:
            client = self._clients.pop(name, None)
        if client:
            client.stop()

    def stop_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.stop()


# Process-wide manager (the bridge is a single long-running process).
_MANAGER: McpClientManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> McpClientManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = McpClientManager()
        return _MANAGER
