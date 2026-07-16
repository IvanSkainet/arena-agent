"""ngrok tunnel admin runtime helpers (v4.32.0).

Third-party fallback transport alongside Tailscale, ZeroTier,
and cloudflared. ngrok is the industry-standard tunnel: a single
static binary, a public HTTPS URL from ``*.ngrok-free.app`` (free
tier) or a custom domain (paid), and — the differentiator — a
built-in local HTTP API at ``http://127.0.0.1:4040/api/tunnels``
that reports the tunnel URL as structured JSON. That means we
don't have to grep stdout the way we do for cloudflared; we can
poll the local API and parse a stable response shape.

Environment tunables (all optional, all typo-safe):
  * ``ARENA_NGROK_AUTHTOKEN``  -- passed to ``ngrok config
    add-authtoken`` on start if the user hasn't already
    configured one. Free tier requires an authtoken (unlike
    cloudflared quick tunnels).
  * ``ARENA_NGROK_URL_WAIT_SECONDS`` -- override the URL-wait
    timeout (default 30s, clamped 1--300s -- same defaults as
    the v4.24.1 cloudflared fix).
  * ``ARENA_NGROK_REGION`` -- ``us`` / ``eu`` / ``ap`` / ``au`` /
    ``sa`` / ``jp`` / ``in`` -- passed as ``--region``.

Public API (mirrors cloudflared.py::cloudflared_funnel_action):
    ngrok_action("start" | "stop" | "status", port, *,
                 root_agent, subprocess_kwargs) -> dict

State shape identical to cloudflared for uniform snapshot
consumption downstream:
    NGROK_STATE = {"proc": Popen | None, "url": str, "log": [str]}
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.admin.binaries import which_windows_or_path

NGROK_STATE: dict[str, Any] = {"proc": None, "url": "", "log": []}

# ---------------------------------------------------------------------------
# Wait-timeout tunable (mirrors v4.24.1 cloudflared clamp/env pattern)
# ---------------------------------------------------------------------------
_URL_WAIT_MIN_SECONDS = 1.0
_URL_WAIT_MAX_SECONDS = 300.0
# v4.36.2: bumped from 30s -> 45s. Live-smoke of v4.36.1 saw an
# ngrok cold start hit exactly 30.0s and only barely make it. The
# ngrok edge is measurably slower to negotiate a URL than cloudflared
# on the same box, so we give it more head-room. Same env override
# available for operators on faster/slower networks.
_URL_WAIT_DEFAULT_SECONDS = 45.0
_URL_WAIT_POLL_INTERVAL_SECONDS = 0.5
_ENV_URL_WAIT = "ARENA_NGROK_URL_WAIT_SECONDS"


def _url_wait_seconds() -> float:
    """Read ARENA_NGROK_URL_WAIT_SECONDS, clamp, return. Same
    30s default and 1--300s clamp as the v4.24.1 cloudflared fix
    -- gives cold ngrok launches room to negotiate an
    ngrok-free.app URL without another live-smoke false negative."""
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


# ---------------------------------------------------------------------------
# Binary resolution -- same system-first / bundled fallback as cloudflared
# ---------------------------------------------------------------------------
def _system_candidates() -> list[str]:
    system = platform.system()
    if system == "Windows":
        return [
            r"C:\Program Files\ngrok\ngrok.exe",
            r"C:\Program Files (x86)\ngrok\ngrok.exe",
        ]
    if system == "Darwin":
        return [
            "/usr/local/bin/ngrok",
            "/opt/homebrew/bin/ngrok",
        ]
    return [
        "/usr/local/bin/ngrok",
        "/snap/bin/ngrok",
    ]


def _resolve_ngrok_with_source(root_agent: Path) -> tuple[str | None, str]:
    """Resolve ngrok binary and its source (``system`` /
    ``bundled`` / ``not_found``)."""
    system_bin = which_windows_or_path("ngrok", _system_candidates())
    if system_bin:
        return system_bin, "system"
    for candidate in _system_candidates():
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate, "system"
    local = Path(root_agent) / ("ngrok.exe" if platform.system() == "Windows"
                                else "ngrok")
    if local.exists():
        return str(local), "bundled"
    return None, "not_found"


def _get_ngrok_version(bin_path: str) -> str | None:
    try:
        result = subprocess.run(
            [bin_path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        # Output: "ngrok version 3.14.0"
        match = re.search(r"version\s+([\d.]+)", result.stdout or "")
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def _get_update_hint(source: str, version: str | None) -> str:
    system = platform.system()
    if source == "system":
        if system == "Linux":
            return ("Update via your package manager, or download the latest "
                    "from https://ngrok.com/download.")
        if system == "Darwin":
            return "Update via Homebrew: `brew upgrade ngrok/ngrok/ngrok`."
        if system == "Windows":
            return ("Update via `winget upgrade ngrok.ngrok` or download the "
                    "latest MSI from https://ngrok.com/download")
        return "Download the latest from https://ngrok.com/download"
    if source == "bundled":
        return ("Bundled binary managed by Arena. Run: "
                "`python3 scripts/update_bundled_tools.py ngrok`")
    # not_found
    if system == "Windows":
        return ("Install ngrok: `winget install --id ngrok.ngrok` or "
                "`scoop install ngrok`. Docs: https://ngrok.com/download")
    if system == "Darwin":
        return ("Install ngrok: `brew install ngrok/ngrok/ngrok`. "
                "Docs: https://ngrok.com/download")
    return ("Install ngrok, e.g. `sudo snap install ngrok` or download from "
            "https://ngrok.com/download")


# ---------------------------------------------------------------------------
# Local API polling -- ngrok's differentiator vs cloudflared
# ---------------------------------------------------------------------------
NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"


def _poll_ngrok_url_from_api(timeout: float = 2.0,
                              expected_port: int | None = None) -> str | None:
    """Query ngrok's built-in local HTTP API for OUR tunnel URL.

    v4.36.1: filter tunnels by ``config.addr`` (must contain
    ``:<expected_port>``) so we don't accidentally return a URL
    from an unrelated ngrok session running on the same host.
    Live-smoke of v4.36.0 caught this: an operator can have a
    long-running ngrok pointing at port 80, and our probe was
    returning that URL instead of the one for our bridge port,
    then the response 502'd because the addr didn't match.

    When ``expected_port`` is None, falls back to the pre-v4.36.1
    behaviour (any HTTPS tunnel). Preserves backward compat for
    callers that don't care about port-matching.
    """
    try:
        with urllib.request.urlopen(NGROK_LOCAL_API, timeout=timeout) as resp:
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    except Exception:
        return None
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None
    tunnels = payload.get("tunnels") or []
    if not isinstance(tunnels, list):
        return None

    def _matches_our_port(t: dict) -> bool:
        if expected_port is None:
            return True
        cfg = t.get("config") or {}
        addr = str(cfg.get("addr") or "")
        # ngrok's addr is usually http://localhost:8765 or
        # 127.0.0.1:8765 or bare 8765. Check for :<port> substring
        # occurrence -- guards against false positives like port
        # 80 accidentally matching 8080.
        return f":{expected_port}" in addr or addr == str(expected_port)

    # First pass: HTTPS + matches our port.
    for t in tunnels:
        if not isinstance(t, dict):
            continue
        url = t.get("public_url") or ""
        if url.startswith("https://") and _matches_our_port(t):
            return url
    # Second pass: any protocol + matches our port.
    for t in tunnels:
        if isinstance(t, dict) and t.get("public_url") and _matches_our_port(t):
            return str(t["public_url"])
    return None


def _ngrok_monitor_thread(proc: subprocess.Popen, port: int) -> None:
    """Drain the child stdout so the pipe doesn't fill and block
    the tunnel. Also captures URLs from stdout as a secondary
    signal (some ngrok versions log the URL to stdout even before
    the local API is ready)."""
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            break
        line_str = line.strip()
        NGROK_STATE["log"].append(line_str)
        if len(NGROK_STATE["log"]) > 100:
            NGROK_STATE["log"].pop(0)
        # Ngrok logs an "url=https://..." field in its structured logs.
        m = re.search(r"https?://[a-zA-Z0-9-]+\.(?:ngrok-free\.app|ngrok\.io|ngrok\.dev)",
                      line_str)
        if m and not NGROK_STATE["url"]:
            NGROK_STATE["url"] = m.group(0)


def _terminate_ngrok(timeout: int = 5) -> None:
    proc = NGROK_STATE["proc"]
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _apply_authtoken(bin_path: str, subprocess_kwargs: Callable[[], dict[str, Any]]) -> None:
    """If ARENA_NGROK_AUTHTOKEN is set, run ``ngrok config
    add-authtoken <TOKEN>`` before start. No-op when already
    configured -- ngrok is idempotent on this call."""
    token = os.environ.get("ARENA_NGROK_AUTHTOKEN", "").strip()
    if not token:
        return
    try:
        subprocess.run(
            [bin_path, "config", "add-authtoken", token],
            capture_output=True, timeout=10,
            **subprocess_kwargs(),
        )
    except Exception:
        pass  # Non-fatal -- ngrok will surface auth errors from `start`.


# ---------------------------------------------------------------------------
# Error classification -- v4.36.0
# ---------------------------------------------------------------------------
# Map ngrok's stdout/stderr patterns to short structured error codes so
# callers (dashboard, agentctl, autostart hook) can react without
# grepping free-form English strings. Each code carries a human hint
# that names the exact fix.
_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # (regex fragment, error_code, human hint)
    (r"ERR_NGROK_4018|session is not authenticated",
     "needs_authtoken",
     "ngrok needs an authtoken. Free tier at "
     "https://dashboard.ngrok.com/get-started/your-authtoken -- then set "
     "ARENA_NGROK_AUTHTOKEN in the arena-bridge service env, or run "
     "`ngrok config add-authtoken <TOKEN>` once as the bridge user."),
    (r"ERR_NGROK_108|simultaneously.*limit|only 1 simultaneous",
     "session_limit_hit",
     "ngrok free tier allows only one active session per account. Stop "
     "the other ngrok process, or upgrade the account."),
    (r"ERR_NGROK_3200|invalid authtoken|token.*not valid",
     "invalid_authtoken",
     "The ARENA_NGROK_AUTHTOKEN value is not accepted by ngrok. "
     "Re-copy from https://dashboard.ngrok.com/get-started/your-authtoken."),
    (r"ERR_NGROK_121|region.*not.*valid|unknown region",
     "invalid_region",
     "ARENA_NGROK_REGION is not one of us/eu/ap/au/sa/jp/in. Unset it "
     "or pick a valid region."),
    (r"ERR_NGROK_3204|too many.*tunnels",
     "tunnel_limit_hit",
     "Free ngrok tier is limited on concurrent tunnels; stop the extras "
     "or upgrade."),
    (r"address already in use|bind:.*4040",
     "api_port_in_use",
     "ngrok's local API port 4040 is already bound by another process "
     "(often a leftover ngrok). Kill it with `pkill -f ngrok`."),
]


def _classify_error(log_lines: list[str]) -> tuple[str, str]:
    """Scan the last N log lines and return (error_code, hint).

    Returns (``"unknown"``, generic-hint) when no pattern matches --
    the raw log is still passed through in the caller, so nothing is
    lost; this classifier just extracts a first-class actionable
    handle for the common cases."""
    text = "\n".join(log_lines).lower()
    for pattern, code, hint in _ERROR_PATTERNS:
        if re.search(pattern.lower(), text):
            return code, hint
    return ("unknown",
            "See the log field for ngrok's raw output. "
            "Docs: https://ngrok.com/docs/errors/")


def _start_ngrok(bin_path: str, port: int, *,
                 subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if NGROK_STATE["proc"] and NGROK_STATE["proc"].poll() is None:
        return {"ok": True, "action": "start", "already_running": True,
                "url": NGROK_STATE["url"]}

    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()

    _apply_authtoken(bin_path, subprocess_kwargs)

    argv = [bin_path, "http", str(port), "--log=stdout",
            "--log-format=logfmt"]
    region = os.environ.get("ARENA_NGROK_REGION", "").strip()
    if region:
        argv.extend(["--region", region])

    try:
        NGROK_STATE["proc"] = subprocess.Popen(
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
        target=_ngrok_monitor_thread,
        args=(NGROK_STATE["proc"], port),
        daemon=True,
    )
    thread.start()

    # Wait for URL to appear -- try the local API first (fast + reliable),
    # fall back to whatever the stdout monitor captured.
    # v4.36.0: fail-fast when the child process dies before we ever
    # see a URL. Previously we swallowed the die-event with a bare
    # `break` and still reported "timed out after 30s" -- misleading
    # when the truth was "died at 1.5s because no authtoken". Now
    # we return immediately with a classified error code.
    total_wait = _url_wait_seconds()
    deadline = time.monotonic() + total_wait
    process_died_early = False
    while time.monotonic() < deadline:
        # Prefer the local API which has a stable JSON shape.
        # v4.36.1: filter by ``expected_port=port`` so we don't
        # accidentally pick up a URL from another ngrok session
        # running against a different port on the same host.
        api_url = _poll_ngrok_url_from_api(timeout=0.5, expected_port=port)
        if api_url:
            NGROK_STATE["url"] = api_url
            break
        # Fall back to stdout regex capture.
        if NGROK_STATE["url"]:
            break
        if NGROK_STATE["proc"].poll() is not None:
            # Give the monitor thread one more beat to drain any
            # final stderr/stdout lines that describe the failure.
            time.sleep(_URL_WAIT_POLL_INTERVAL_SECONDS)
            process_died_early = True
            break
        time.sleep(_URL_WAIT_POLL_INTERVAL_SECONDS)

    if not NGROK_STATE["url"]:
        elapsed = time.monotonic() - (deadline - total_wait)
        _terminate_ngrok(timeout=2)
        NGROK_STATE["proc"] = None
        error_code, hint = _classify_error(list(NGROK_STATE["log"]))
        if process_died_early:
            msg = (f"ngrok exited after {elapsed:.1f}s before opening a "
                   f"tunnel. Reason: {error_code}. {hint}")
        else:
            msg = (f"ngrok timed out generating a tunnel URL after "
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
            "log": list(NGROK_STATE["log"]),
        }

    return {
        "ok": True,
        "action": "start",
        "port": port,
        "url": NGROK_STATE["url"],
        "waited_seconds": total_wait,
        "log": list(NGROK_STATE["log"]),
    }


def ngrok_action(action: str, port: int, *,
                 root_agent: Path,
                 subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Same public shape as cloudflared_funnel_action: start / stop / status."""
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    bin_path, source = _resolve_ngrok_with_source(root_agent)

    if action == "start":
        if not bin_path:
            return {"ok": False, "error": "ngrok binary not found",
                    "update_hint": _get_update_hint(source, None)}
        return _start_ngrok(bin_path, port, subprocess_kwargs=subprocess_kwargs)

    if action == "stop":
        _terminate_ngrok()
        NGROK_STATE["proc"] = None
        NGROK_STATE["url"] = ""
        return {"ok": True, "action": "stop"}

    # action == "status"
    proc = NGROK_STATE["proc"]
    running = proc is not None and proc.poll() is None
    installed = bin_path is not None
    version = _get_ngrok_version(bin_path) if bin_path else None

    # v4.36.1: if we're NOT running any more but NGROK_STATE["url"]
    # still holds a stale value (from a prior start that later
    # died, or from a previous session's API-poll), clear it so
    # /status doesn't report a URL that leads nowhere. Prevents
    # the "active:false but url:https://..." contradiction the
    # live-smoke of v4.36.0 caught.
    if not running and NGROK_STATE["url"]:
        NGROK_STATE["url"] = ""

    # If we think we're running, double-check by polling the local API.
    # Handles the case where the child was killed out-of-band.
    # v4.36.1: pass expected_port=port so we only surface OUR tunnel
    # if another unrelated ngrok session is also live on the box.
    if running and not NGROK_STATE["url"]:
        api_url = _poll_ngrok_url_from_api(timeout=1.0, expected_port=port)
        if api_url:
            NGROK_STATE["url"] = api_url

    result = {
        "ok": True,
        "action": "status",
        "installed": installed,
        "source": source,
        "version": version,
        "active": running,
        "url": NGROK_STATE["url"],
        "log": list(NGROK_STATE["log"]) if running else [],
    }
    if installed:
        result["update_hint"] = _get_update_hint(source, version)
    return result
