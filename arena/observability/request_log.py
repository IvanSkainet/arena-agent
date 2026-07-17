"""Request/response JSONL log helpers.

Privacy posture (v4.44.0)
-------------------------
The request log records every HTTP hit's ``(ts, method, path,
status, duration, peer, error)``. Operators use it to spot
error spikes and slow endpoints; a co-tenant or bug-report
recipient using it as an operator-behaviour tracker is a
privacy failure mode.

Two dials operators can turn:

* ``ARENA_LOG_PEER=0`` -- omit the ``peer`` field entirely.
  Path + status + duration remain (needed for debugging), but
  the request-to-IP association is not persisted.
* ``ARENA_LOG_PEER=mask`` -- hash the peer with a per-install
  salt (stable across bridge restarts because the salt is
  derived from the master token; different across installs).
  Enough to see "how many distinct peers hit this endpoint"
  without recording the actual addresses.
* default -- full peer, matching pre-v4.44.0 behaviour.

The log file itself is chmod 0o600 (v4.44.0 fix -- previously
default umask 0o644 which meant any co-tenant could read the
operator's HTTP history). See v4.40.0 for the ``~/.arena/*``
discipline the request log now matches.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

request_log_lock = threading.Lock()
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


def _peer_privacy_mode() -> str:
    """Resolve the peer-logging mode from ``ARENA_LOG_PEER``.

    Returns one of ``"full"`` (default), ``"mask"``, or ``"off"``.
    Case-insensitive. Truthy-off shapes for the ``"off"`` mode:
    ``0`` / ``false`` / ``no`` / ``off``. The literal ``"mask"``
    enables hashed-peer mode. Anything else = full.
    """
    raw = os.environ.get("ARENA_LOG_PEER", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return "off"
    if raw == "mask":
        return "mask"
    return "full"


def _mask_peer(peer: str) -> str:
    """Deterministic per-install hash of a peer address.

    Salted with ``ARENA_LOG_PEER_SALT`` (falling back to a
    fixed derivation that only matters relative to itself --
    all we need is per-install stability so ``count distinct
    peers`` stays meaningful within one bridge's log). The
    output is a short prefix -- enough to distinguish "many
    peers" from "one peer hammering us" without letting an
    attacker enumerate a reasonable IP space back to plaintext.
    """
    salt = os.environ.get("ARENA_LOG_PEER_SALT",
                          "arena-request-log-salt-v1").encode("utf-8")
    h = hashlib.sha256(salt + peer.encode("utf-8", "replace")).hexdigest()
    return f"peer:{h[:12]}"


def log_request_response(
    *,
    log_file: Path,
    app_dir: Path,
    utc_now_fn: Callable[[], str],
    method: str,
    path: str,
    status: int,
    duration: float,
    req_id: str,
    peer: str = "",
    error: str = "",
    lock: threading.Lock = request_log_lock,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """Append one request/response entry and rotate if necessary.

    v4.44.0: honours ``ARENA_LOG_PEER`` for peer-address
    privacy (``off`` / ``mask`` / default full). See module
    docstring for rationale.
    """
    # v4.45.0: route error strings through the shared redaction
    # helper. HTTP handler errors sometimes echo the request body
    # or an exception message that captured a bearer token; the
    # request log was previously the last place those could leak
    # to (audit log already scrubs). Path is redacted too because
    # a client-supplied route with an embedded token (?token=...
    # stripped by aiohttp Request.path but path segments like
    # /v1/agent-<id>-<token-hex> could still carry one) would
    # otherwise persist verbatim.
    from arena.observability.redact import redact_string
    entry: dict[str, Any] = {
        "ts": utc_now_fn(),
        "req_id": req_id,
        "method": method,
        "path": redact_string(path),
        "status": status,
        "duration_ms": round(duration * 1000, 2),
    }
    mode = _peer_privacy_mode()
    if peer and mode == "full":
        entry["peer"] = peer
    elif peer and mode == "mask":
        entry["peer"] = _mask_peer(peer)
    # mode == "off" -> peer field omitted entirely
    if error:
        entry["error"] = redact_string(error[:500])
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > max_bytes:
            for i in range(backup_count, 0, -1):
                old = app_dir / f"requests.jsonl.{i}"
                older = app_dir / f"requests.jsonl.{i + 1}"
                if old.exists():
                    if i == backup_count:
                        old.unlink()
                    else:
                        try:
                            old.rename(older)
                            # v4.44.0: re-apply 0o600 after rename.
                            try:
                                os.chmod(older, 0o600)
                            except Exception:
                                pass
                        except OSError:
                            pass
            try:
                rotated = app_dir / "requests.jsonl.1"
                log_file.rename(rotated)
                try:
                    os.chmod(rotated, 0o600)
                except Exception:
                    pass
            except OSError:
                pass
        with lock:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # v4.44.0: enforce owner-only mode on the request log,
            # matching the discipline the audit log has had since
            # v3.something. requests.jsonl entries contain peer IPs,
            # request paths, and error strings that can leak
            # infrastructure topology + operator behaviour to any
            # co-tenant on the machine.
            try:
                import os as _os
                _os.chmod(log_file, 0o600)
            except Exception:
                pass
    except Exception:
        pass


def read_request_log(
    log_file: Path,
    *,
    lines_count: int = 100,
    method_filter: str = "",
    path_filter: str = "",
    status_filter: str = "",
) -> list[dict[str, Any]]:
    """Read filtered request log entries, most recent first."""
    entries: list[dict[str, Any]] = []
    lines_count = min(max(1, lines_count), 1000)
    method_filter = (method_filter or "").upper()
    path_filter = path_filter or ""
    status_filter = status_filter or ""
    try:
        if not log_file.exists():
            return []
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(all_lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if method_filter and entry.get("method", "").upper() != method_filter:
                continue
            if path_filter and path_filter not in entry.get("path", ""):
                continue
            if status_filter:
                try:
                    if entry.get("status", 0) != int(status_filter):
                        continue
                except ValueError:
                    pass
            entries.append(entry)
            if len(entries) >= lines_count:
                break
    except Exception:
        return entries
    return entries


# Backward-compatible private alias.
_log_request_response = log_request_response
