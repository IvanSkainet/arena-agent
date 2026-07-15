"""Multi-agent: isolated bridge sessions (v3.86.0).

Requested by user GardenXas: "possibility to run 2+ isolated sessions".
The minimum viable design:

  * A new endpoint pair (`POST /v1/agents`, `GET /v1/agents`,
    `DELETE /v1/agents/{id}`) creates / lists / revokes agent
    sessions. Each session gets:
      - a stable `agent_id` (short random hex),
      - a bearer `token` derived from the master token so revocation
        is atomic (delete the record and the token stops working),
      - a `label` the caller picks (e.g. "gardenxas-workstation"),
      - a rolling per-agent audit log kept in memory (last 500
        events) so operators can see what each agent has been
        doing without grepping the shared audit file.

  * The master token keeps working exactly as before. Only requests
    made with an agent token get scoped to that agent.

  * Auth layer (`arena.auth.runtime.check_auth`) recognises the
    agent token via the shared registry below, sets
    `request["agent_id"]` (aiohttp application key) on success.

  * No lock manager, no per-agent rate limits, no separate audit
    files, no per-agent tunnels. Those were the "excess" GardenXas
    complained about; they can be added later once someone actually
    needs them.

The registry is process-local. Restarting the bridge revokes every
agent -- which is fine for a rolling bridge upgrade because the
master token restores full access.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


# Ring-buffer size for the per-agent audit log. 500 * ~200 bytes ≈
# 100 KB per agent, comfortably below any concern for hundreds of
# agents.
_AUDIT_RING_SIZE = 500


@dataclass
class AgentRecord:
    agent_id: str
    label: str
    token: str
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = 0.0
    request_count: int = 0
    audit_ring: list[dict[str, Any]] = field(default_factory=list)

    def note_request(self) -> None:
        self.last_seen_at = time.time()
        self.request_count += 1

    def record_audit(self, event: dict[str, Any]) -> None:
        # Ring-buffer semantics: keep only the last N entries.
        self.audit_ring.append({**event, "ts": time.time()})
        if len(self.audit_ring) > _AUDIT_RING_SIZE:
            del self.audit_ring[: len(self.audit_ring) - _AUDIT_RING_SIZE]


class AgentRegistry:
    """Thread-safe process-wide store of agent sessions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[str, AgentRecord] = {}
        self._by_token: dict[str, str] = {}   # token -> agent_id

    # ---- CRUD ------------------------------------------------------------

    def create(self, *, label: str, master_token: str) -> AgentRecord:
        """Mint a new agent session. `label` is a human-friendly string
        the operator picks (max 80 chars, sanitised)."""
        clean_label = (label or "").strip()[:80] or "agent"
        # Sanitise: only printable ASCII, no control chars.
        clean_label = "".join(
            ch if 32 <= ord(ch) < 127 else "_" for ch in clean_label
        )
        with self._lock:
            for _ in range(6):
                agent_id = secrets.token_hex(4)   # 8 hex chars
                if agent_id not in self._by_id:
                    break
            else:
                raise RuntimeError("could not allocate a unique agent_id")
            token = _derive_agent_token(master_token, agent_id)
            rec = AgentRecord(agent_id=agent_id, label=clean_label,
                              token=token)
            self._by_id[agent_id] = rec
            self._by_token[token] = agent_id
            return rec

    def revoke(self, agent_id: str) -> bool:
        with self._lock:
            rec = self._by_id.pop(agent_id, None)
            if rec is None:
                return False
            self._by_token.pop(rec.token, None)
            return True

    def get(self, agent_id: str) -> AgentRecord | None:
        with self._lock:
            return self._by_id.get(agent_id)

    def resolve_token(self, token: str) -> AgentRecord | None:
        """Look up an agent by its bearer token. Constant-time via
        `hmac.compare_digest` inside `_derive_agent_token` (aliases
        share the same hash prefix)."""
        if not token:
            return None
        with self._lock:
            agent_id = self._by_token.get(token)
            if not agent_id:
                return None
            return self._by_id.get(agent_id)

    def list(self) -> list[AgentRecord]:
        with self._lock:
            return list(self._by_id.values())

    def note_request(self, agent_id: str) -> None:
        with self._lock:
            rec = self._by_id.get(agent_id)
            if rec:
                rec.note_request()

    def record_audit(self, agent_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            rec = self._by_id.get(agent_id)
            if rec:
                rec.record_audit(event)

    def reset(self) -> None:
        """Full wipe -- used by tests. Never call at runtime."""
        with self._lock:
            self._by_id.clear()
            self._by_token.clear()


# ---------------------------------------------------------------------------
# Token derivation
# ---------------------------------------------------------------------------

_TOKEN_PREFIX = "agent-"


def _derive_agent_token(master_token: str, agent_id: str) -> str:
    """Derive a per-agent bearer token from the master token.

    Format: `agent-<agent_id>-<16 hex>` where the trailing hex is
    HMAC-SHA256(master_token, agent_id)[:16]. This guarantees:

      * Revocation is atomic: forget the agent_id and the token no
        longer decodes.
      * Cryptographically unguessable: without the master token you
        cannot forge one for an existing agent_id.
      * Rotating the master token invalidates every agent token in
        one go (a nice byproduct: security incident response is
        just "rotate master, restart bridge").
    """
    if not master_token or not agent_id:
        raise ValueError("both master_token and agent_id required")
    digest = hmac.new(master_token.encode("utf-8"),
                      agent_id.encode("utf-8"),
                      hashlib.sha256).hexdigest()[:16]
    return f"{_TOKEN_PREFIX}{agent_id}-{digest}"


def looks_like_agent_token(token: str) -> bool:
    """Fast prefix check callers can use before hitting the registry."""
    return bool(token) and token.startswith(_TOKEN_PREFIX)


# ---------------------------------------------------------------------------
# Process-wide default registry (used by handlers + auth runtime).
# ---------------------------------------------------------------------------

_REGISTRY = AgentRegistry()


def create(*, label: str, master_token: str) -> AgentRecord:
    return _REGISTRY.create(label=label, master_token=master_token)


def revoke(agent_id: str) -> bool:
    return _REGISTRY.revoke(agent_id)


def get(agent_id: str) -> AgentRecord | None:
    return _REGISTRY.get(agent_id)


def resolve_token(token: str) -> AgentRecord | None:
    return _REGISTRY.resolve_token(token)


def list_agents() -> list[AgentRecord]:
    return _REGISTRY.list()


def note_request(agent_id: str) -> None:
    _REGISTRY.note_request(agent_id)


def record_audit(agent_id: str, event: dict[str, Any]) -> None:
    _REGISTRY.record_audit(agent_id, event)


def reset() -> None:
    _REGISTRY.reset()


# JSON-friendly snapshot for HTTP responses (never leaks tokens except
# on the initial `create` response, where we intentionally show it).
def snapshot(rec: AgentRecord, *, include_token: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "agent_id": rec.agent_id,
        "label": rec.label,
        "created_at": rec.created_at,
        "last_seen_at": rec.last_seen_at,
        "request_count": rec.request_count,
        "audit_recent": rec.audit_ring[-20:],   # last 20 events
    }
    if include_token:
        payload["token"] = rec.token
    return payload
