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

import atexit
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from arena.jsonshape import loads_object

# Commands the client is allowed to spawn. Mirrors the marketplace `test`
# allowlist so a tampered mcp.json cannot run an arbitrary binary. Full paths
# are permitted as long as their basename (sans .exe/.cmd/.bat) is allowed --
# this lets a git-venv server register its own venv interpreter
# (e.g. .../venv/Scripts/python.exe) while still blocking arbitrary binaries.
ALLOWED_COMMANDS = ("npx", "uvx", "uv", "python", "python3", "node")

log = logging.getLogger("arena.mcp_client")

# Bounds on what a third-party MCP server may push at us (bug #59).
#
# A JSON-RPC frame legitimately carries tool output, so the ceiling has to
# be generous -- 4 MB is far more than any real `tools/list` or tool result
# and still small enough that a runaway server cannot exhaust memory one
# line at a time.
_MAX_LINE_CHARS = 4 * 1024 * 1024
# Depth of the pending-output queue. A request reads until it sees its own
# `id`, so a backlog this deep already means the server is talking past
# anyone listening. Bounded at 1000 lines the worst case is ~4 GB in
# theory but ~a few MB in practice, versus unbounded before.
_STDOUT_QUEUE_DEPTH = 1000


def _command_allowed(command: str) -> bool:
    if command in ALLOWED_COMMANDS:
        return True
    base = os.path.basename(command.replace("\\", "/")).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base in ALLOWED_COMMANDS or re.fullmatch(r"python\d+(?:\.\d+)?", base) is not None

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
        # v4.148.0: tag spawned children so orphaned MCP servers from a
        # previous (crashed/restarted) bridge can be identified and reaped.
        self.env = {**os.environ, **(env or {}), "ARENA_MCP_CHILD": "1"}
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self._stdout_q: queue.Queue[str | None] = queue.Queue(
            maxsize=_STDOUT_QUEUE_DEPTH)
        self._reader_thread: threading.Thread | None = None
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
        self._start_reader()
        resp = self.request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": _CLIENT_INFO,
        }, timeout=timeout)
        self.server_info = resp.get("result", {})
        self._notify("notifications/initialized")
        return self.server_info


    def _start_reader(self) -> None:
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return
        assert self.proc and self.proc.stdout

        def _reader() -> None:
            assert self.proc and self.proc.stdout
            dropped = 0
            try:
                for line in self.proc.stdout:
                    # v4.164.0 (bug #59): neither the line length nor the
                    # queue depth was bounded, so a third-party MCP server
                    # -- `npx some-server` off the internet -- could grow
                    # this process without limit. Measured with a stub
                    # that answers `initialize` and then streams 100 KB
                    # lines: RSS went from 13 MB to 1433 MB in four
                    # seconds, 14,933 lines queued. A hostile server is
                    # one way to get there; a buggy one that loops on
                    # stderr-to-stdout is the likelier one.
                    if len(line) > _MAX_LINE_CHARS:
                        # A JSON-RPC frame this large is not a response we
                        # can use. Truncating would produce invalid JSON
                        # that the parser skips anyway, so drop it and say
                        # so once rather than pretend.
                        dropped += 1
                        if dropped == 1:
                            log.warning(
                                "mcp[%s]: dropping oversized output line "
                                "(%d chars > %d); the server is not "
                                "speaking usable JSON-RPC",
                                self.command, len(line), _MAX_LINE_CHARS)
                        continue
                    try:
                        self._stdout_q.put_nowait(line)
                    except queue.Full:
                        # Backlog means nobody is reading: the caller has
                        # moved on, or the server is chattier than any
                        # consumer. Dropping the oldest keeps the newest
                        # response reachable, which is what a request
                        # waiting on `id` actually needs.
                        dropped += 1
                        try:
                            self._stdout_q.get_nowait()
                            self._stdout_q.put_nowait(line)
                        except (queue.Empty, queue.Full):
                            pass
            except Exception:
                pass
            finally:
                if dropped:
                    log.warning("mcp[%s]: dropped %d output line(s)",
                                self.command, dropped)
                try:
                    self._stdout_q.put_nowait(None)
                except queue.Full:
                    # Make room for the EOF marker: a reader blocked on
                    # `get()` must still learn the server is gone.
                    try:
                        self._stdout_q.get_nowait()
                        self._stdout_q.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass

        self._reader_thread = threading.Thread(
            target=_reader, name="arena-mcp-stdout-reader", daemon=True)
        self._reader_thread.start()

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
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.stop()
                    raise McpError(f"MCP '{method}' timed out after {timeout}s; server stopped")
                try:
                    line = self._stdout_q.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if line is None:  # EOF: server closed stdout (died)
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

    # -- MCP conveniences --------------------------------------------------
    def list_tools(self, timeout: float = 30, refresh: bool = False) -> list[dict[str, Any]]:
        if self._tools is not None and not refresh:
            return self._tools
        resp = self.request("tools/list", {}, timeout=timeout)
        if "error" in resp:
            raise McpError(f"tools/list error: {resp['error']}")
        raw_tools = resp.get("result", {}).get("tools", [])
        self._tools = [dict(t) for t in raw_tools] if isinstance(raw_tools, list) else []
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

    # -- v4.148.0: orphan tracking / reaping ---------------------------------
    # stdio MCP servers are children of the bridge process. When the bridge is
    # restarted (notably by the auto-updater) without a clean shutdown, those
    # children survive as orphans and accumulate across versions. We record a
    # pidfile per spawned server and reap any whose spawning bridge is dead.
    def _run_dir(self) -> Path:
        d = self.config_path.parent / "run"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", name)

    def _pidfile(self, name: str) -> Path:
        return self._run_dir() / f"{self._safe_name(name)}.json"

    def _record_pidfile(self, name: str, client: McpStdioClient) -> None:
        try:
            pid = client.proc.pid if client.proc else None
            if not pid:
                return
            rec = {
                "name": name,
                "pid": int(pid),
                "bridge_pid": int(os.getpid()),
                "started": time.time(),
                "command": client.command,
            }
            self._pidfile(name).write_text(json.dumps(rec), encoding="utf-8")
        except Exception:
            pass  # tracking is best-effort; never block a tool call

    def _clear_pidfile(self, name: str) -> None:
        try:
            self._pidfile(name).unlink()
        except Exception:
            pass

    def reap_orphans(self) -> dict[str, Any]:
        """Terminate stdio MCP servers spawned by a now-dead bridge.

        Safe to call at startup and before spawning. For each pidfile we only
        act when the recorded ``bridge_pid`` is no longer alive (the owner is
        gone) and the child's creation time is consistent with the recorded
        spawn (guards against PID reuse). Servers owned by another live bridge
        instance, or by this process, are left untouched.
        """
        import psutil  # type: ignore

        reaped: list[int] = []
        skipped: list[int] = []
        me = os.getpid()
        for pf in self._run_dir().glob("*.json"):
            try:
                rec = json.loads(pf.read_text(encoding="utf-8"))
            except Exception:
                try:
                    pf.unlink()
                except Exception:
                    pass
                continue
            child_pid = rec.get("pid")
            bridge_pid = rec.get("bridge_pid")
            started = rec.get("started") or 0
            name = rec.get("name") or pf.stem
            if not isinstance(child_pid, int):
                try:
                    pf.unlink()
                except Exception:
                    pass
                continue
            try:
                proc = psutil.Process(child_pid)
            except psutil.NoSuchProcess:
                self._clear_pidfile(name)  # child already gone -> stale marker
                continue
            except Exception:
                skipped.append(child_pid)
                continue
            # Leave servers owned by a still-running bridge (ours or another).
            if bridge_pid == me:
                continue
            try:
                if psutil.pid_exists(int(bridge_pid)):
                    continue  # another live bridge owns this server
            except Exception:
                pass
            # PID-reuse guard: only reap if the live proc was created around
            # the recorded spawn time (within a generous window).
            try:
                if abs(proc.create_time() - float(started)) > 86400:
                    skipped.append(child_pid)
                    self._clear_pidfile(name)
                    continue
            except Exception:
                pass
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                reaped.append(child_pid)
            except Exception:
                skipped.append(child_pid)
            self._clear_pidfile(name)
        return {"ok": True, "reaped": reaped, "skipped": skipped}

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                return loads_object(self.config_path.read_text(encoding="utf-8"),
                                    default={"mcpServers": {}})
            except json.JSONDecodeError:
                return {"mcpServers": {}}
        return {"mcpServers": {}}

    def servers(self) -> dict[str, dict[str, Any]]:
        """Return the configured servers (name -> config)."""
        return self._load_config().get("mcpServers", {})

    def get_client(self, name: str) -> McpStdioClient:
        # v4.148.0: clean up orphans left by a previous bridge run before we
        # (possibly) spawn a fresh server for the same name. Best-effort.
        try:
            self.reap_orphans()
        except Exception:
            pass
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
            self._record_pidfile(name, client)
            return client

    def list_tools(self, name: str, refresh: bool = False, timeout: float = 30) -> list[dict[str, Any]]:
        return self.get_client(name).list_tools(refresh=refresh, timeout=timeout)

    def call_tool(self, name: str, tool: str,
                  arguments: dict[str, Any] | None = None, timeout: float = 180) -> dict[str, Any]:
        return self.get_client(name).call_tool(tool, arguments, timeout=timeout)

    def status(self, name: str) -> dict[str, Any]:
        client = self._clients.get(name)
        return {"registered": name in self.servers(),
                "running": bool(client and client.alive())}

    def stop(self, name: str) -> None:
        with self._lock:
            client = self._clients.pop(name, None)
        if client:
            client.stop()
        self._clear_pidfile(name)

    def stop_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.stop()
        # v4.148.0: clear our own pidfiles on a clean shutdown so the next
        # bridge start does not mistake freshly-reaped servers for orphans.
        for pf in self._run_dir().glob("*.json"):
            try:
                pf.unlink()
            except Exception:
                pass


# Process-wide manager (the bridge is a single long-running process).
_MANAGER: McpClientManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> McpClientManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = McpClientManager()
            # v4.148.0: tear down spawned MCP servers on a normal interpreter
            # exit so they do not leak across bridge restarts. Forced kills
            # (auto-update SIGKILL) are still caught by startup reaping.
            try:
                atexit.register(_atexit_stop_all)
            except Exception:
                pass
        return _MANAGER


def _atexit_stop_all() -> None:
    try:
        if _MANAGER is not None:
            _MANAGER.stop_all()
    except Exception:
        pass
