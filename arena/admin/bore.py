"""bore tunnel admin runtime helpers (v4.47.0).

Fifth transport, sibling to Tailscale, ZeroTier, cloudflared and
ngrok. bore is a tiny Rust TCP tunnel maintained by Eric Zhang
(https://github.com/ekzhang/bore, MIT). It stands out for four
reasons this project actually cares about:

* **Zero account required.** ``bore.pub`` is a free public relay
  operated by the project. No signup, no authtoken, no dashboard
  cookie. That is a deliberate design goal for arena-bridge --
  operators asked for a fallback transport that just works after
  ``cargo install bore-cli`` (or a single release binary drop)
  without touching a browser first.
* **Static, dependency-free binary.** Ships as a single Rust
  binary. No dynamic runtime, no config file mandatory on first
  run. Same "system-first / bundled fallback" resolution strategy
  we use for cloudflared / ngrok works verbatim.
* **TCP-only.** bore relays raw TCP; it doesn't terminate TLS.
  For us that is a feature: the bridge already speaks HTTPS on
  port 8765, so a client that dials ``https://bore.pub:<remote>``
  gets the bridge's real self-signed cert -- which agents already
  pin via ``ARENA_BRIDGE_PIN_SHA256`` (see v4.45.0). No middlebox
  can silently substitute a cert the way a full HTTPS reverse
  proxy could.
* **Predictable startup logs.** Emits ``listening at
  <server>:<remote_port>`` on stdout as soon as the tunnel is
  live. Parse-friendly, no local HTTP API to poll.

Environment tunables (all optional, all typo-safe):

  * ``ARENA_BORE_SERVER``           -- default ``bore.pub``.
    Override to point at a self-hosted ``bore server``.
  * ``ARENA_BORE_URL_WAIT_SECONDS`` -- default 30s, clamped
    1--300s -- same shape as the v4.24.1 cloudflared clamp and
    the v4.36.2 ngrok clamp.
  * ``ARENA_BORE_LOCAL_HOST``       -- default ``localhost``.
    ``bore`` needs to know what host to point at on the loopback
    side; overridable in case the bridge binds a non-loopback
    interface.
  * ``ARENA_BORE_SECRET``           -- optional shared secret,
    passed as ``--secret <value>``. Both client and server must
    agree. ``bore.pub`` does not require one; self-hosted
    ``bore server --secret`` deployments do.
  * ``ARENA_BORE_REMOTE_PORT``      -- optional. Default is 0
    (server picks a random remote port). Set to a specific
    number to request it via ``--port <N>``; the server may or
    may not honour it.

Public API (mirrors ``cloudflared.py::cloudflared_funnel_action``
and ``ngrok.py::ngrok_action`` so the dashboard, autostart hook
and wiring layer can treat all five transports uniformly):

    bore_action("start" | "stop" | "status", port, *,
                root_agent, subprocess_kwargs) -> dict

State shape kept identical to the earlier siblings so downstream
snapshot code (``tunnels._bore_snapshot``) doesn't need any
transport-specific special-casing:

    BORE_STATE = {"proc": Popen | None, "url": str, "log": [str]}
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.admin.binaries import which_windows_or_path

BORE_STATE: dict[str, Any] = {"proc": None, "url": "", "log": []}

# ---------------------------------------------------------------------------
# Wait-timeout tunable (same 1--300s clamp as cloudflared / ngrok)
# ---------------------------------------------------------------------------
_URL_WAIT_MIN_SECONDS = 1.0
_URL_WAIT_MAX_SECONDS = 300.0
_URL_WAIT_DEFAULT_SECONDS = 30.0
_URL_WAIT_POLL_INTERVAL_SECONDS = 0.5
_ENV_URL_WAIT = "ARENA_BORE_URL_WAIT_SECONDS"

_DEFAULT_BORE_SERVER = "bore.pub"
_DEFAULT_LOCAL_HOST = "localhost"


def _url_wait_seconds() -> float:
    """Read ARENA_BORE_URL_WAIT_SECONDS, clamp, return.

    bore tunnels typically come up in under a second; the 30s
    default is a generous safety margin that matches cloudflared
    / ngrok so operators see uniform behaviour across transports.
    """
    raw = os.environ.get(_ENV_URL_WAIT, "").strip()
    if not raw:
        return _URL_WAIT_DEFAULT_SECONDS
    try:
        val = float(raw)
    except ValueError:
        return _URL_WAIT_DEFAULT_SECONDS
    if val < _URL_WAIT_MIN_SECONDS:
        return _URL_WAIT_MIN_SECONDS
    if val > _URL_WAIT_MAX_SECONDS:
        return _URL_WAIT_MAX_SECONDS
    return val


def _bore_server() -> str:
    """Configured bore server host -- default ``bore.pub``."""
    val = os.environ.get("ARENA_BORE_SERVER", "").strip()
    return val or _DEFAULT_BORE_SERVER


def _bore_local_host() -> str:
    """Loopback host name bore should forward to."""
    val = os.environ.get("ARENA_BORE_LOCAL_HOST", "").strip()
    return val or _DEFAULT_LOCAL_HOST


def _bore_secret() -> str:
    return os.environ.get("ARENA_BORE_SECRET", "").strip()


def _bore_remote_port() -> int:
    """Preferred remote port -- 0 means "let the server choose"."""
    raw = os.environ.get("ARENA_BORE_REMOTE_PORT", "").strip()
    if not raw:
        return 0
    try:
        val = int(raw)
    except ValueError:
        return 0
    if val < 0 or val > 65535:
        return 0
    return val


# ---------------------------------------------------------------------------
# Binary resolution -- same system-first / bundled fallback as ngrok
# ---------------------------------------------------------------------------
def _system_candidates() -> list[str]:
    system = platform.system()
    if system == "Windows":
        return [
            r"C:\Program Files\bore\bore.exe",
            r"C:\Program Files (x86)\bore\bore.exe",
        ]
    if system == "Darwin":
        return [
            "/usr/local/bin/bore",
            "/opt/homebrew/bin/bore",
        ]
    return [
        "/usr/local/bin/bore",
        # Rust binaries installed via `cargo install bore-cli` land
        # under ~/.cargo/bin -- resolved at call time so tests
        # running under a different HOME don't need to monkey-patch
        # this list.
        str(Path.home() / ".cargo/bin/bore"),
        "/snap/bin/bore",
    ]


def _resolve_bore_with_source(root_agent: Path) -> tuple[str | None, str]:
    """Resolve bore binary and its source (``system`` /
    ``bundled`` / ``not_found``)."""
    system_bin = which_windows_or_path("bore", _system_candidates())
    if system_bin:
        return system_bin, "system"
    for candidate in _system_candidates():
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate, "system"
    local = Path(root_agent) / ("bore.exe" if platform.system() == "Windows"
                                else "bore")
    if local.exists():
        return str(local), "bundled"
    return None, "not_found"


def _get_bore_version(bin_path: str) -> str | None:
    try:
        result = subprocess.run(
            [bin_path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        # Output: "bore 0.6.0" or "bore-cli 0.5.1"
        match = re.search(r"([\d]+\.[\d]+\.[\d]+)", result.stdout or "")
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def _get_update_hint(source: str, version: str | None) -> str:
    system = platform.system()
    if source == "system":
        return ("Update via `cargo install bore-cli` -- or download the "
                "latest release binary from https://github.com/ekzhang/bore/releases")
    if source == "bundled":
        return ("Bundled binary managed by Arena. Run: "
                "`python3 scripts/update_bundled_tools.py bore`")
    # not_found
    if system == "Windows":
        return ("Install bore: download the Windows release binary from "
                "https://github.com/ekzhang/bore/releases and place it in "
                "PATH, or install Rust and run `cargo install bore-cli`.")
    if system == "Darwin":
        return ("Install bore: `cargo install bore-cli` (requires Rust), "
                "or download from https://github.com/ekzhang/bore/releases")
    return ("Install bore: `cargo install bore-cli` (requires Rust), or "
            "download the release binary from "
            "https://github.com/ekzhang/bore/releases")


# ---------------------------------------------------------------------------
# stdout parsing -- bore emits "listening at <server>:<port>" as soon as the
# remote port is negotiated.
# ---------------------------------------------------------------------------
_LISTEN_RE = re.compile(
    r"listening at ([A-Za-z0-9.\-]+):(\d{1,5})",
    re.IGNORECASE,
)


def _bore_monitor_thread(proc: subprocess.Popen, port: int) -> None:
    """Drain the child stdout so the pipe doesn't fill, and
    capture the negotiated remote port from the first
    ``listening at <server>:<port>`` line."""
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            break
        line_str = line.strip()
        BORE_STATE["log"].append(line_str)
        if len(BORE_STATE["log"]) > 100:
            BORE_STATE["log"].pop(0)
        if BORE_STATE["url"]:
            continue
        match = _LISTEN_RE.search(line_str)
        if match:
            host = match.group(1)
            remote_port = match.group(2)
            # Serve the URL as https:// so downstream clients dial the
            # bridge's real TLS endpoint through the raw TCP relay.
            # bore itself is transport-agnostic; ArenaBridge speaks
            # HTTPS on the loopback port, so the outward-facing URL is
            # https://<server>:<remote_port>.
            BORE_STATE["url"] = f"https://{host}:{remote_port}"


def _terminate_bore(timeout: int = 5) -> None:
    proc = BORE_STATE["proc"]
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Error classification -- mirrors the ngrok classifier shape.
# ---------------------------------------------------------------------------
_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    (r"authentication failed|invalid secret|secret mismatch",
     "invalid_secret",
     "The ARENA_BORE_SECRET value does not match the bore server's "
     "``--secret``. Re-copy the shared secret or unset "
     "ARENA_BORE_SECRET when connecting to bore.pub."),
    (r"connection refused|no route to host|dns error|failed to lookup",
     "server_unreachable",
     "Cannot reach the bore server. Check network connectivity or "
     "point ARENA_BORE_SERVER at a reachable host."),
    (r"port \d+ is not available|address already in use",
     "remote_port_conflict",
     "The requested remote port is already in use on the bore server. "
     "Unset ARENA_BORE_REMOTE_PORT so the server picks a free port, "
     "or pick a different one."),
]


def _classify_error(log_lines: list[str]) -> tuple[str, str]:
    """Scan the last N log lines and return (error_code, hint)."""
    text = "\n".join(log_lines).lower()
    for pattern, code, hint in _ERROR_PATTERNS:
        if re.search(pattern.lower(), text):
            return code, hint
    return ("unknown",
            "See the log field for bore's raw output. "
            "Docs: https://github.com/ekzhang/bore#readme")


# ---------------------------------------------------------------------------
# Start / stop / status
# ---------------------------------------------------------------------------
def _start_bore(bin_path: str, port: int, *,
                subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if BORE_STATE["proc"] and BORE_STATE["proc"].poll() is None:
        return {"ok": True, "action": "start", "already_running": True,
                "url": BORE_STATE["url"]}

    BORE_STATE["url"] = ""
    BORE_STATE["log"].clear()

    server = _bore_server()
    local_host = _bore_local_host()
    secret = _bore_secret()
    remote_port = _bore_remote_port()

    # ``bore local <port> --to <server> [--secret S] [--port N] [--local-host H]``
    # is the canonical CLI. All arguments are static literals or come
    # from env vars we sanitise above, so there is no shell injection
    # vector -- argv-form only.
    argv = [bin_path, "local", str(port), "--to", server,
            "--local-host", local_host,
            "--port", str(remote_port)]
    if secret:
        argv.extend(["--secret", secret])

    try:
        BORE_STATE["proc"] = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            **subprocess_kwargs(),
        )
    except Exception as e:
        return {"ok": False, "action": "start", "error": str(e),
                "error_code": "spawn_failed"}

    thread = threading.Thread(
        target=_bore_monitor_thread,
        args=(BORE_STATE["proc"], port),
        daemon=True,
    )
    thread.start()

    total_wait = _url_wait_seconds()
    deadline = time.monotonic() + total_wait
    process_died_early = False
    while time.monotonic() < deadline:
        if BORE_STATE["url"]:
            break
        if BORE_STATE["proc"].poll() is not None:
            # Give the monitor thread one more beat to drain
            # any final stderr/stdout lines describing the
            # failure -- same pattern as ngrok's v4.36.0 fix.
            time.sleep(_URL_WAIT_POLL_INTERVAL_SECONDS)
            process_died_early = True
            break
        time.sleep(_URL_WAIT_POLL_INTERVAL_SECONDS)

    if not BORE_STATE["url"]:
        elapsed = time.monotonic() - (deadline - total_wait)
        _terminate_bore(timeout=2)
        BORE_STATE["proc"] = None
        error_code, hint = _classify_error(list(BORE_STATE["log"]))
        if process_died_early:
            msg = (f"bore exited after {elapsed:.1f}s before opening a "
                   f"tunnel. Reason: {error_code}. {hint}")
        else:
            msg = (f"bore timed out generating a tunnel URL after "
                   f"{total_wait:.1f}s. Classifier: {error_code}. {hint}")
        return {
            "ok": False,
            "action": "start",
            "error": msg,
            "error_code": error_code,
            "hint": hint,
            "process_died_early": process_died_early,
            "elapsed_seconds": round(elapsed, 2),
            "waited_seconds": total_wait,
            "server": server,
            "log": list(BORE_STATE["log"]),
        }

    return {
        "ok": True,
        "action": "start",
        "port": port,
        "url": BORE_STATE["url"],
        "server": server,
        "waited_seconds": total_wait,
        "log": list(BORE_STATE["log"]),
    }


def bore_action(action: str, port: int, *,
                root_agent: Path,
                subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Public entry-point, same shape as ``cloudflared_funnel_action``
    and ``ngrok_action`` (start / stop / status)."""
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    bin_path, source = _resolve_bore_with_source(root_agent)

    if action == "start":
        if not bin_path:
            return {"ok": False, "error": "bore binary not found",
                    "update_hint": _get_update_hint(source, None)}
        return _start_bore(bin_path, port,
                           subprocess_kwargs=subprocess_kwargs)

    if action == "stop":
        _terminate_bore()
        BORE_STATE["proc"] = None
        BORE_STATE["url"] = ""
        return {"ok": True, "action": "stop"}

    # action == "status"
    proc = BORE_STATE["proc"]
    running = proc is not None and proc.poll() is None
    installed = bin_path is not None
    version = _get_bore_version(bin_path) if bin_path else None

    # Clear stale URL when the process has died -- matches the
    # v4.36.1 ngrok fix that prevented "active:false but url:..."
    # contradictions.
    if not running and BORE_STATE["url"]:
        BORE_STATE["url"] = ""

    result = {
        "ok": True,
        "action": "status",
        "installed": installed,
        "source": source,
        "version": version,
        "active": running,
        "url": BORE_STATE["url"],
        "server": _bore_server(),
        "log": list(BORE_STATE["log"]) if running else [],
    }
    if installed:
        result["update_hint"] = _get_update_hint(source, version)
    return result
