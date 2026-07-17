"""ZeroTier Central API client (v3.96.0).

Local ZeroTier CLI/HTTP (arena/admin/zerotier.py) manages the
*node*: which networks this host has joined. Central manages the
*network*: who owns it, which member nodes are authorized, which
IP ranges are handed out, etc. Both are needed for full
"take a node, put it on a network, done" workflows.

Central API root: https://api.zerotier.com/api/v1/
Auth: `Authorization: Bearer <api-token>`

Token discovery (in order):

1. Environment variable ``ZEROTIER_CENTRAL_TOKEN``.
2. File pointed to by ``ZEROTIER_CENTRAL_TOKEN_FILE``.
3. Default file ``~/.zerotier-central-token`` (first line stripped).

This mirrors how the local ZeroTier CLI resolves ``authtoken.secret``
so operators aren't surprised by discovery precedence.

Every helper here returns a plain ``dict`` with an ``ok`` flag so
handlers can pass the payload straight through without branching
on exceptions. Errors carry a ``reason`` string plus, when known,
the HTTP ``status`` code, so the Dashboard can render a useful
message instead of a generic 500.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CENTRAL_API = "https://api.zerotier.com/api/v1"
HTTP_TIMEOUT = 15

# Match a 10-hex-char member node ID (address of a ZeroTier node).
_NODE_ID_RE = re.compile(r"^[0-9a-f]{10}$")
# Match a 16-hex-char network ID.
_NET_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _token_candidates() -> list[str]:
    """Return the ordered list of paths to check for the token."""
    hits: list[str] = []
    env_file = os.environ.get("ZEROTIER_CENTRAL_TOKEN_FILE")
    if env_file:
        hits.append(env_file)
    hits.append(str(Path.home() / ".zerotier-central-token"))
    return hits


def read_central_token() -> tuple[str | None, str | None]:
    """Return ``(token, source_description)`` or ``(None, reason)``.

    ``source_description`` is a short human-readable string for the
    Dashboard's diagnostics popup (e.g. ``"env"`` or the file path).
    """
    env_token = os.environ.get("ZEROTIER_CENTRAL_TOKEN", "").strip()
    if env_token:
        return env_token, "env:ZEROTIER_CENTRAL_TOKEN"
    for path in _token_candidates():
        try:
            p = Path(path).expanduser()
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            first = text.splitlines()[0].strip() if text else ""
            if first:
                return first, f"file:{p}"
        except OSError:
            continue
    return None, (
        "no token found — set ZEROTIER_CENTRAL_TOKEN, "
        "ZEROTIER_CENTRAL_TOKEN_FILE, or write ~/.zerotier-central-token"
    )


def _request(
    method: str,
    path: str,
    token: str,
    body: Any = None,
    timeout: int = HTTP_TIMEOUT,
) -> tuple[int, Any, str | None]:
    """Return ``(status, json_body, error_message)``.

    JSON body is always a Python object (dict/list) on 2xx; on any
    other status we still try to parse the body as JSON so callers
    can surface Central's own error text.

    Any transport-layer failure returns ``(0, None, error_message)``
    so callers can distinguish "network down" from "server said no".
    """
    url = f"{CENTRAL_API}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        # Central expects the User-Agent to identify the client;
        # we set an Arena-specific one so their audit logs can
        # trace requests back to us if anything's ever wrong.
        "User-Agent": "arena-unified-bridge",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- fixed my.zerotier.com Central API URL  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw or None
        return e.code, parsed, str(e)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, None, f"{type(e).__name__}: {e}"

    try:
        parsed = json.loads(raw) if raw else None
    except Exception:
        parsed = raw or None
    return status, parsed, None


def _ok_status(status: int) -> bool:
    return 200 <= status < 300


def _no_token_response() -> dict[str, Any]:
    _, reason = read_central_token()
    return {
        "ok": False,
        "central": False,
        "error": "ZeroTier Central token not configured",
        "reason": reason,
        "hint": (
            "Create an API token on https://my.zerotier.com/account "
            "and store it in one of: env ZEROTIER_CENTRAL_TOKEN, "
            "env ZEROTIER_CENTRAL_TOKEN_FILE, or "
            "~/.zerotier-central-token"
        ),
    }


# --- Network-level operations -------------------------------------------


def list_networks() -> dict[str, Any]:
    """GET /network — return every network owned by the token."""
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request("GET", "/network", token)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    networks = _summarise_networks(body if isinstance(body, list) else [])
    return {
        "ok": True,
        "central": True,
        "token_source": source,
        "count": len(networks),
        "networks": networks,
    }


def get_network(network_id: str) -> dict[str, Any]:
    """GET /network/{id} — full detail for one network."""
    if not _NET_ID_RE.fullmatch((network_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"network_id must be 16 hex chars, got {network_id!r}"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request("GET", f"/network/{network_id.lower()}", token)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    return {"ok": True, "central": True, "token_source": source,
            "network": body}


def create_network(name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST /network — create a new network. Only ``name`` is required;
    the rest of the ZeroTier defaults (private=True, v4 auto-assign
    from 10.147.17.0/24, ...) apply automatically.

    Callers who want a specific IP range can pass ``config`` matching
    Central's schema, e.g.::

        {"config": {"ipAssignmentPools": [
            {"ipRangeStart": "10.99.0.10", "ipRangeEnd": "10.99.0.200"}
        ]}}
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "central": True,
                "error": "name required to create a network"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    payload: dict[str, Any] = {"config": {"name": name}}
    if config and isinstance(config, dict):
        # Shallow-merge: caller-provided keys under "config" override.
        for k, v in (config.get("config") or {}).items():
            payload["config"][k] = v
        # Top-level extras (e.g. description) go straight through.
        for k, v in config.items():
            if k != "config":
                payload[k] = v
    status, body, err = _request("POST", "/network", token, body=payload)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    return {"ok": True, "central": True, "token_source": source,
            "network": body}


def delete_network(network_id: str) -> dict[str, Any]:
    """DELETE /network/{id} — permanently delete the network.

    Central returns 200 with an empty body on success. There is no
    undo — any joined members immediately disconnect.
    """
    if not _NET_ID_RE.fullmatch((network_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"network_id must be 16 hex chars, got {network_id!r}"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request("DELETE", f"/network/{network_id.lower()}", token)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    return {"ok": True, "central": True, "token_source": source,
            "network_id": network_id.lower(), "status": status}


# --- Member-level operations --------------------------------------------


def list_members(network_id: str) -> dict[str, Any]:
    """GET /network/{id}/member — every node ever joined."""
    if not _NET_ID_RE.fullmatch((network_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"network_id must be 16 hex chars, got {network_id!r}"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request("GET", f"/network/{network_id.lower()}/member", token)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    members = _summarise_members(body if isinstance(body, list) else [])
    return {
        "ok": True, "central": True, "token_source": source,
        "network_id": network_id.lower(),
        "count": len(members),
        "authorized_count": sum(1 for m in members if m.get("authorized")),
        "members": members,
    }


def update_member(
    network_id: str,
    node_id: str,
    *,
    authorized: bool | None = None,
    name: str | None = None,
    description: str | None = None,
    ip_assignments: list[str] | None = None,
) -> dict[str, Any]:
    """POST /network/{nwid}/member/{nodeId} — approve/deny/rename/pin IP.

    All parameters are optional; only the ones passed will be sent
    to Central, so this doubles as ``approve``, ``deauthorize``,
    ``rename``, and ``set_ip`` depending on which args are used.
    """
    if not _NET_ID_RE.fullmatch((network_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"network_id must be 16 hex chars, got {network_id!r}"}
    if not _NODE_ID_RE.fullmatch((node_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"node_id must be 10 hex chars, got {node_id!r}"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()

    payload: dict[str, Any] = {}
    config: dict[str, Any] = {}
    if authorized is not None:
        config["authorized"] = bool(authorized)
    if ip_assignments is not None:
        config["ipAssignments"] = [str(x).strip() for x in ip_assignments if str(x).strip()]
    if config:
        payload["config"] = config
    if name is not None:
        payload["name"] = str(name)
    if description is not None:
        payload["description"] = str(description)
    if not payload:
        return {"ok": False, "central": True,
                "error": "nothing to update — pass at least one of "
                         "authorized/name/description/ip_assignments"}

    status, body, err = _request(
        "POST", f"/network/{network_id.lower()}/member/{node_id.lower()}",
        token, body=payload,
    )
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    return {"ok": True, "central": True, "token_source": source,
            "network_id": network_id.lower(),
            "node_id": node_id.lower(),
            "applied": payload,
            "member": body}


def delete_member(network_id: str, node_id: str) -> dict[str, Any]:
    """DELETE /network/{nwid}/member/{nodeId} — remove from Central.

    The member can re-join later (Central just forgets it). Use
    ``update_member(authorized=False)`` if you want them to remain
    in the list but be blocked.
    """
    if not _NET_ID_RE.fullmatch((network_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"network_id must be 16 hex chars, got {network_id!r}"}
    if not _NODE_ID_RE.fullmatch((node_id or "").lower()):
        return {"ok": False, "central": True,
                "error": f"node_id must be 10 hex chars, got {node_id!r}"}
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request(
        "DELETE", f"/network/{network_id.lower()}/member/{node_id.lower()}", token,
    )
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    return {"ok": True, "central": True, "token_source": source,
            "network_id": network_id.lower(),
            "node_id": node_id.lower(),
            "status": status}


# --- Diagnostics --------------------------------------------------------


def central_status() -> dict[str, Any]:
    """Quick "is the token OK" check for the Dashboard header. Hits
    ``GET /status`` on Central (identity endpoint) and returns
    account info + rate-limit tier if available."""
    token, source = read_central_token()
    if not token:
        return _no_token_response()
    status, body, err = _request("GET", "/status", token)
    if err and status == 0:
        return {"ok": False, "central": True, "error": "unreachable",
                "reason": err, "token_source": source}
    if not _ok_status(status):
        return {"ok": False, "central": True, "status": status,
                "error": _extract_error(body) or "central returned non-2xx",
                "body": body, "token_source": source}
    # /status body typically: {"online": true, "clusterNode": "...", ...}
    return {
        "ok": True, "central": True, "token_source": source,
        "status": body if isinstance(body, dict) else {"raw": body},
    }


# --- Helpers ------------------------------------------------------------


def _extract_error(body: Any) -> str | None:
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            v = body.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return None


def _summarise_networks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact per-row projection for the Dashboard table. The full
    Central payload is huge (~4KB/network with rules etc.); return
    only the fields humans actually scan."""
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cfg = it.get("config") or {}
        out.append({
            "id": it.get("id"),
            "name": cfg.get("name") or "",
            "description": it.get("description") or "",
            "private": bool(cfg.get("private", True)),
            "member_count": it.get("totalMemberCount") or 0,
            "authorized_count": it.get("authorizedMemberCount") or 0,
            "creation_time": it.get("creationTime"),
            "last_modified": it.get("lastModified"),
            "v4_assign_mode": cfg.get("v4AssignMode") or {},
            "v6_assign_mode": cfg.get("v6AssignMode") or {},
            "ip_pools": cfg.get("ipAssignmentPools") or [],
        })
    return out


def _summarise_members(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cfg = it.get("config") or {}
        # last_online is a UNIX-ms timestamp on Central; leave as-is
        # so the Dashboard can render "X minutes ago" with the same
        # helper it already has for other timestamps.
        out.append({
            "node_id": it.get("nodeId") or it.get("id"),
            "name": it.get("name") or "",
            "description": it.get("description") or "",
            "authorized": bool(cfg.get("authorized", False)),
            "hidden": bool(it.get("hidden", False)),
            "physical_address": it.get("physicalAddress") or "",
            "client_version": it.get("clientVersion") or "",
            "last_online": it.get("lastOnline"),
            "ip_assignments": cfg.get("ipAssignments") or [],
            "no_auto_assign_ips": bool(cfg.get("noAutoAssignIps", False)),
        })
    return out
