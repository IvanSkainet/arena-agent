"""ZeroTier network admin runtime helpers.

Cross-platform strategy (works out of the box on Windows/macOS/Linux):

1. Prefer the ZeroTier local HTTP API at 127.0.0.1:9993. It is authoritative,
   available on every ZeroTier install, and the same on all platforms. The
   auth token is read once from the well-known per-platform path.

2. Fall back to the `zerotier-cli` binary if the HTTP token cannot be read.
   The binary is looked up in PATH first, then in a small set of
   platform-specific well-known locations (including Windows Program Files,
   macOS `/Applications`, and Linux `/usr/sbin`).

3. If a NOPASSWD sudo wrapper (`zerotier-cli-wrapper`) exists it is also
   accepted. This lets Linux users escape the default 640 permissions on
   `authtoken.secret` by installing a small opt-in wrapper — but we no
   longer *prefer* it, so nothing about this module is Linux-specific.

The module never invokes sudo directly and never mutates system state during
`status` calls, so it is safe to expose via /v1/capabilities on every host.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

HTTP_API = "http://127.0.0.1:9993"
HTTP_TIMEOUT = 3.0

# On Windows, hide the console window when we spawn zerotier-cli.bat/.exe.
# Without this flag every 5-second Dashboard auto-refresh would pop a CMD
# flash for a fraction of a second — annoying and looks like malware.
_SUBPROCESS_KWARGS: dict[str, Any] = {}
if platform.system().lower() == "windows":
    _SUBPROCESS_KWARGS["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


# ---------------------------------------------------------------------------
# Auth-token discovery (per-platform)
# ---------------------------------------------------------------------------
def _token_candidates() -> list[str]:
    """Return the well-known authtoken.secret paths for this platform."""
    system = platform.system().lower()
    candidates: list[str] = []

    # Explicit override always wins.
    env = os.environ.get("ZEROTIER_AUTHTOKEN_PATH")
    if env:
        candidates.append(env)

    if system == "windows":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates += [
            os.path.join(program_data, "ZeroTier", "One", "authtoken.secret"),
            r"C:\ProgramData\ZeroTier\One\authtoken.secret",
        ]
        # Per-user copy created by GUI on first launch.
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "ZeroTier", "One", "authtoken.secret"))
    elif system == "darwin":
        candidates += [
            "/Library/Application Support/ZeroTier/One/authtoken.secret",
        ]
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, "Library", "Application Support", "ZeroTier", "One", "authtoken.secret"))
    else:  # Linux / *BSD
        candidates += [
            "/var/lib/zerotier-one/authtoken.secret",
            "/etc/zerotier-one/authtoken.secret",
        ]
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".zeroTier-one/authtoken.secret"))

    # Dedup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _read_token() -> tuple[str | None, str | None]:
    """Return (token, path) or (None, None) if no readable token was found."""
    for path in _token_candidates():
        try:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="ascii", errors="ignore") as f:
                token = f.read().strip()
            if token:
                return token, path
        except (PermissionError, OSError):
            continue
    return None, None


def _install_hint() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "Install ZeroTier for Windows: https://www.zerotier.com/download/"
    if system == "darwin":
        return "Install ZeroTier for macOS: brew install --cask zerotier-one  (or https://www.zerotier.com/download/)"
    return (
        "Install ZeroTier for Linux (e.g. `sudo pacman -S zerotier-one`, "
        "`sudo apt install zerotier-one`) — see https://www.zerotier.com/download/"
    )


def _permission_hint(missing_reason: str) -> str:
    system = platform.system().lower()
    if system == "windows":
        return "Run the Bridge as the same user that installed ZeroTier, or as an administrator."
    if system == "darwin":
        return "Grant the Bridge process access to /Library/Application Support/ZeroTier/One/, or run it under the ZeroTier admin account."
    # Linux fallback: two options.
    return (
        "Either (a) allow the Bridge user to read the ZeroTier authtoken: "
        "`sudo chmod 640 /var/lib/zerotier-one/authtoken.secret && sudo usermod -aG zerotier-one $USER` "
        "(re-login after), or (b) install the optional sudo wrapper: "
        "`echo \"$USER ALL=(root) NOPASSWD: /usr/bin/zerotier-cli\" | sudo tee /etc/sudoers.d/zerotier "
        "&& sudo install -m 0755 /dev/stdin /usr/local/bin/zerotier-cli-wrapper <<< "
        "'#!/bin/bash\\nexec sudo /usr/bin/zerotier-cli \"$@\"'`."
    ) + f" Underlying error: {missing_reason}."


# ---------------------------------------------------------------------------
# HTTP API path (preferred, cross-platform)
# ---------------------------------------------------------------------------
def _http_get(path: str, token: str) -> dict[str, Any] | list[Any] | None:
    req = urllib.request.Request(f"{HTTP_API}{path}", headers={"X-ZT1-Auth": token})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
        return json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None


def _status_via_http(token: str) -> dict[str, Any] | None:
    node = _http_get("/status", token)
    if not isinstance(node, dict):
        return None
    networks = _http_get("/network", token)
    networks_list: list[dict[str, Any]] = []
    if isinstance(networks, list):
        for net in networks:
            if not isinstance(net, dict):
                continue
            networks_list.append({
                "nwid": net.get("nwid") or net.get("id") or "",
                "id": net.get("id") or net.get("nwid") or "",
                "name": net.get("name") or "",
                "mac": net.get("mac") or "",
                "status": net.get("status") or "",
                "type": net.get("type") or "",
                "active": (net.get("status") or "").upper() == "OK",
                "assignedAddresses": net.get("assignedAddresses") or [],
                "portDeviceName": net.get("portDeviceName") or "",
            })
    return {
        "node_id": node.get("address") or "",
        "version": node.get("version") or "",
        "online": bool(node.get("online")),
        "connected": bool(node.get("online")) or bool(node.get("tcpFallbackActive")),
        "world_id": node.get("worldId"),
        "networks": networks_list,
    }


# ---------------------------------------------------------------------------
# CLI fallback (still cross-platform: PATH lookup + a few well-known paths)
# ---------------------------------------------------------------------------
def _cli_candidates() -> list[str]:
    system = platform.system().lower()
    names = ["zerotier-cli"]
    if system == "windows":
        names = ["zerotier-cli.bat", "zerotier-cli.exe", "zerotier-cli"]
    paths: list[str] = []
    for name in names:
        found = shutil.which(name)
        if found:
            paths.append(found)
    if system == "windows":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        # The .bat is what the installer registers; .exe is the same tool
        # available directly. Both work with the same argument set.
        for base in (program_files, program_files_x86):
            for name in ("zerotier-cli.bat", "zerotier-cli.exe"):
                paths.append(os.path.join(base, "ZeroTier", "One", name))
    elif system == "darwin":
        paths += [
            "/usr/local/bin/zerotier-cli",
            "/opt/homebrew/bin/zerotier-cli",
            "/Applications/ZeroTier One.app/Contents/MacOS/zerotier-cli",
        ]
    else:  # Linux / *BSD
        paths += [
            "/usr/sbin/zerotier-cli",
            "/usr/bin/zerotier-cli",
            "/usr/local/bin/zerotier-cli",
        ]
        # Optional sudo wrapper — only tried on Linux, only after the
        # direct binaries. If the user installed a NOPASSWD wrapper to
        # sidestep the default 640 permissions on authtoken.secret, we
        # accept it. Never a wrapper on Windows or macOS.
        if system == "linux":
            paths += [
                "/usr/local/bin/zerotier-cli-wrapper",
                "/usr/bin/zerotier-cli-wrapper",
            ]

    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p and p not in seen and os.path.isfile(p) and os.access(p, os.X_OK):
            seen.add(p)
            out.append(p)
    return out


def _cli_source(path: str) -> str:
    if path.endswith("zerotier-cli-wrapper"):
        return "sudo-wrapper"
    return "direct"


def _run_cli(cli: str, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        **_SUBPROCESS_KWARGS,
    )


_MAC_RE = _re_compile_mac = None  # lazy


def _looks_like_mac(token: str) -> bool:
    """Return True if `token` is an EUI-48 MAC in the form xx:xx:xx:xx:xx:xx."""
    global _MAC_RE
    if _MAC_RE is None:
        import re as _re
        _MAC_RE = _re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")
    return bool(_MAC_RE.match(token))


def _parse_listnetworks(out: str) -> list[dict[str, Any]]:
    """Parse the multi-column output of `zerotier-cli listnetworks`.

    Real-world format is space-separated but the `name` column can be
    empty for networks that have not yet received configuration (e.g.
    right after `zerotier-cli join <nwid>` before the controller
    authorises the node). A `line.split()` collapses runs of whitespace,
    which silently drops the empty name and shifts every subsequent
    column left by one. To detect and repair that, we look at the fifth
    token — if it does not look like a MAC address, the `name` field was
    empty and we back off to a five-column layout.
    """
    networks: list[dict[str, Any]] = []
    for line in (out or "").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 6 or parts[1] != "listnetworks":
            continue
        # Header row has literal <placeholder> tokens.
        if parts[2].startswith("<") or parts[3].startswith("<"):
            continue

        # Detect the "empty name" case: expected layout is
        # [200, listnetworks, nwid, name, mac, status, type, dev, ips]
        # but if `name` was empty the shift makes parts[4] land on `status`
        # ("REQUESTING_CONFIGURATION", "OK", "ACCESS_DENIED", ...) instead
        # of a MAC address.
        name_missing = not _looks_like_mac(parts[4])
        if name_missing:
            name = ""
            mac = ""
            status = parts[4]
            net_type = parts[5] if len(parts) > 5 else ""
            dev = parts[6] if len(parts) > 6 else ""
            ips_raw = parts[7] if len(parts) > 7 else ""
        else:
            name = parts[3]
            mac = parts[4]
            status = parts[5]
            net_type = parts[6] if len(parts) > 6 else ""
            dev = parts[7] if len(parts) > 7 else ""
            ips_raw = parts[8] if len(parts) > 8 else ""

        assigned: list[str] = []
        if ips_raw:
            for ip in ips_raw.split(","):
                ip = ip.strip()
                if ip and ip != "-":
                    assigned.append(ip)

        networks.append({
            "id": parts[2],
            "nwid": parts[2],
            "name": name,
            "mac": mac,
            "status": status,
            "type": net_type,
            "portDeviceName": dev,
            "assignedAddresses": assigned,
            "active": status.upper() == "OK",
        })
    return networks


def _status_via_cli(cli: str) -> dict[str, Any] | tuple[None, str]:
    """Return a status dict via CLI, or (None, error_message) on failure."""
    try:
        proc = _run_cli(cli, ["status"], timeout=10)
    except FileNotFoundError:
        return (None, f"binary vanished: {cli}")
    except subprocess.TimeoutExpired:
        return (None, "zerotier-cli status timed out")
    if proc.returncode != 0:
        return (None, (proc.stderr or proc.stdout or f"exit={proc.returncode}").strip())

    text = (proc.stdout or "").strip()
    parts = text.split()
    node_id = parts[2] if len(parts) > 2 else ""
    version = parts[3] if len(parts) > 3 else ""
    connected = "ONLINE" in text.upper() or "TUNNELED" in text.upper()

    networks: list[dict[str, Any]] = []
    try:
        lp = _run_cli(cli, ["listnetworks"], timeout=10)
        if lp.returncode == 0:
            networks = _parse_listnetworks(lp.stdout or "")
    except Exception:
        pass

    return {
        "node_id": node_id,
        "version": version,
        "online": connected,
        "connected": connected,
        "networks": networks,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def zerotier_status(*, subprocess_kwargs: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return the current ZeroTier state in a platform-agnostic shape.

    Response shape (stable):
      {
        "ok": bool,
        "installed": bool,
        "backend": "http" | "cli" | "none",
        "cli_source": "direct" | "sudo-wrapper" | None,
        "cli_path": str | None,
        "authtoken_path": str | None,
        "platform": "windows" | "darwin" | "linux" | ...,
        "zerotier": {"node_id", "version", "connected", "online"?, "error"?},
        "networks": [ {nwid, name, status, type, active, ...} ],
        "active_count": int,
        "hint": str | None,
      }
    """
    system = platform.system().lower()
    result: dict[str, Any] = {
        "ok": True,
        "installed": False,
        "backend": "none",
        "cli_source": None,
        "cli_path": None,
        "authtoken_path": None,
        "platform": system,
        "zerotier": {},
        "networks": [],
        "active_count": 0,
        "hint": None,
    }

    # ---- Prefer HTTP API ---------------------------------------------------
    token, token_path = _read_token()
    result["authtoken_path"] = token_path
    if token:
        http_result = _status_via_http(token)
        if http_result is not None:
            result["installed"] = True
            result["backend"] = "http"
            result["zerotier"] = {
                "node_id": http_result["node_id"],
                "version": http_result["version"],
                "connected": http_result["connected"],
                "online": http_result["online"],
            }
            result["networks"] = http_result["networks"]
            result["active_count"] = sum(1 for n in result["networks"] if n.get("active"))
            return result
        # Token existed but HTTP failed — the daemon may be down.
        result["zerotier"]["http_error"] = "ZeroTier local API at 127.0.0.1:9993 did not respond"

    # ---- CLI fallback ------------------------------------------------------
    for cli in _cli_candidates():
        cli_result = _status_via_cli(cli)
        if isinstance(cli_result, dict):
            result["installed"] = True
            result["backend"] = "cli"
            result["cli_path"] = cli
            result["cli_source"] = _cli_source(cli)
            result["zerotier"] = {
                "node_id": cli_result["node_id"],
                "version": cli_result["version"],
                "connected": cli_result["connected"],
                "online": cli_result["online"],
            }
            result["networks"] = cli_result["networks"]
            result["active_count"] = sum(1 for n in result["networks"] if n.get("active"))
            return result
        # (None, error) — try next binary.
        _, err = cli_result
        result["zerotier"].setdefault("last_cli_error", err[:400])

    # ---- Nothing worked ---------------------------------------------------
    if not _cli_candidates() and not token:
        # No binary and no token — assume not installed.
        result["ok"] = False
        result["zerotier"]["error"] = "ZeroTier does not appear to be installed"
        result["hint"] = _install_hint()
        return result

    # Installed but unreadable.
    result["ok"] = False
    result["installed"] = True
    reason = result["zerotier"].get("last_cli_error") or result["zerotier"].get("http_error") or "unknown"
    result["zerotier"]["error"] = "ZeroTier is installed but the Bridge cannot read its state"
    result["hint"] = _permission_hint(reason)
    return result


def zerotier_network_action(action: str, network_id: str | None = None) -> dict[str, Any]:
    """Perform a ZeroTier network action.

    Prefers HTTP API (POST/DELETE /network/<nwid>) which works on every OS
    without extra permissions on the local machine.
    """
    action = (action or "").lower()
    if action not in ("join", "leave", "status"):
        return {"ok": False, "error": "action must be join|leave|status"}
    if action in ("join", "leave") and not network_id:
        return {"ok": False, "error": f"network_id required for {action}"}

    # Validate nwid format before doing anything — ZeroTier network IDs are
    # always 16 hex characters. Without this check we happily forward
    # "0000000000000000" or "not-a-real-id" to the CLI which then joins a
    # bogus placeholder network and creates a permanent junk row in
    # `zerotier-cli listnetworks`.
    if action in ("join", "leave") and network_id:
        import re as _re
        clean = network_id.strip().lower()
        if not _re.fullmatch(r"[0-9a-f]{16}", clean):
            return {
                "ok": False,
                "error": (
                    f"network_id must be exactly 16 hex characters "
                    f"(got {network_id!r}, length {len(network_id)})"
                ),
                "action": action,
                "network_id": network_id,
            }
        network_id = clean

    # HTTP path first.
    token, token_path = _read_token()
    if token:
        try:
            if action == "join":
                req = urllib.request.Request(
                    f"{HTTP_API}/network/{network_id}",
                    method="POST",
                    data=b"{}",
                    headers={"X-ZT1-Auth": token, "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    body = resp.read().decode("utf-8", "replace")
                return {"ok": True, "action": "join", "backend": "http", "network_id": network_id, "response": body[:500]}
            if action == "leave":
                req = urllib.request.Request(
                    f"{HTTP_API}/network/{network_id}",
                    method="DELETE",
                    headers={"X-ZT1-Auth": token},
                )
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    body = resp.read().decode("utf-8", "replace")
                return {"ok": True, "action": "leave", "backend": "http", "network_id": network_id, "response": body[:500]}
            if action == "status":
                snap = zerotier_status()
                return {
                    "ok": snap["ok"],
                    "action": "status",
                    "backend": snap["backend"],
                    "networks": snap["networks"],
                    "active_count": snap["active_count"],
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError) as e:
            # Fall through to CLI.
            last_http_error = str(e)
        else:
            last_http_error = ""
    else:
        last_http_error = "no readable authtoken"

    # CLI fallback. Try each candidate; a non-zero exit (typically
    # "authtoken.secret not found or readable") means this binary is not
    # useable for the current process — move on to the next (usually the
    # sudo wrapper on Linux, or a Program Files fallback on Windows).
    last_payload: dict[str, Any] | None = None
    args_by_action = {
        "join": ["join", network_id],
        "leave": ["leave", network_id],
        "status": ["listnetworks"],
    }
    for cli in _cli_candidates():
        try:
            proc = _run_cli(cli, args_by_action[action], timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        payload = {
            "ok": proc.returncode == 0,
            "action": action,
            "backend": "cli",
            "cli_source": _cli_source(cli),
            "cli_path": cli,
            "network_id": network_id,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }
        if action == "status":
            payload["networks"] = _parse_listnetworks(proc.stdout or "") if proc.returncode == 0 else []
            payload["active_count"] = sum(1 for n in payload["networks"] if n["active"])
        if payload["ok"]:
            return payload
        # Keep the most detailed failure so we can return it if every
        # candidate fails.
        last_payload = payload

    if last_payload is not None:
        last_payload["hint"] = _permission_hint(
            (last_payload.get("stderr") or last_payload.get("stdout") or "").strip()[:200]
            or f"cli exit={last_payload.get('exit_code')}"
        )
        return last_payload

    return {
        "ok": False,
        "action": action,
        "error": "ZeroTier is not reachable via HTTP or CLI",
        "http_error": last_http_error,
        "hint": _permission_hint(last_http_error or "no CLI binary found"),
    }
