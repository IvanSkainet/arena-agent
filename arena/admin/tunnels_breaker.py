"""Circuit breaker for the tunnels_probe TCP reachability check (v4.8.0).

Problem: ``_probe_tcp`` waits up to ``timeout`` seconds per provider,
per call. On a host where a provider is silently dead
(Cloudflared quick-tunnel with a stale websocket, ZeroTier LEAF on a
strict-NAT network that just came up, ...) every Dashboard tick and
every ``GET /v1/tunnels/probe`` pays that full timeout again, for a
provider that has been failing for minutes. Multiply by 5-second
Dashboard polling and 3 providers and you get a probe cycle that
routinely takes 4-5s instead of the ~15ms a healthy triple takes.

Fix: a small in-process circuit breaker keyed on ``(provider, host,
port)`` -- three failures in a row and the provider is "open" for
60s. While open, ``allow()`` returns ``False`` and ``describe_open()``
gives an audit-quality reason string so the probe response still
lists the provider, just as ``skip_reason="circuit-breaker open"``
rather than blocking on another timeout.

Configuration (env, both optional):
    ARENA_BREAKER_THRESHOLD  -- consecutive failures before opening;
                                default 3, min 1, max 20
    ARENA_BREAKER_COOLDOWN   -- seconds to stay open before the next
                                probe; default 60.0, min 1.0
    ARENA_BREAKER_DISABLE    -- set to '1' / 'true' / 'yes' to skip
                                the breaker entirely (useful when
                                debugging probe issues)

The implementation is deliberately synchronous and side-effect-free
outside its own ``_STATE`` dict. Every method is safe to call from
async code because the mutations are single-attribute assignments
which are atomic under the GIL, and readers observe the same shape
on every call (no partially-updated records).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


# Defaults; overridable at runtime via env for operators who want
# a tighter or looser policy without a bridge restart.
_DEFAULT_THRESHOLD = 3
_DEFAULT_COOLDOWN = 60.0


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _env_float(name: str, default: float, *, lo: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return default
    return value if value >= lo else lo


def _env_disabled() -> bool:
    raw = (os.environ.get("ARENA_BREAKER_DISABLE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class BreakerRecord:
    """Per-key state. ``opened_at`` is monotonic (safe against wall-
    clock jumps); ``last_error`` is the most recent probe error so
    ``describe_open()`` can tell operators *why* it's open."""
    consecutive_failures: int = 0
    opened_at: float | None = None       # None == closed
    last_error: str | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None


class TunnelsBreaker:
    """A tiny per-key circuit breaker.

    Keys are opaque strings; ``tunnels_probe`` builds them as
    ``"{provider}|{host}:{port}"`` so a provider whose public URL
    moved (Tailscale funnel restarted with a new hostname, quick-
    tunnel reissued) gets a fresh breaker rather than inheriting
    the old state.

    States:
        * closed        -- probes flow, ``allow()`` -> True
        * open          -- ``allow()`` -> False for ``cooldown`` seconds
                            after ``opened_at``
        * half-open     -- once cooldown elapses ``allow()`` -> True
                            again, and the caller records the next
                            outcome (success closes, failure re-opens
                            immediately with the counter kept at
                            threshold so it re-opens cleanly).

    The class is intentionally tiny (~120 lines) and 100% covered
    by ``tests/test_tunnels_breaker.py`` -- do not grow it.
    """

    def __init__(
        self,
        *,
        threshold: int | None = None,
        cooldown: float | None = None,
        clock: Any = None,
    ):
        self._threshold = threshold if threshold is not None else _env_int(
            "ARENA_BREAKER_THRESHOLD", _DEFAULT_THRESHOLD, lo=1, hi=20,
        )
        self._cooldown = cooldown if cooldown is not None else _env_float(
            "ARENA_BREAKER_COOLDOWN", _DEFAULT_COOLDOWN, lo=1.0,
        )
        # ``clock`` lets tests inject a deterministic time source; in
        # production we use ``time.monotonic`` (immune to wall-clock
        # jumps that would otherwise make an "open" breaker either
        # stuck-open or spuriously "recovered").
        self._clock = clock or time.monotonic
        self._state: dict[str, BreakerRecord] = {}

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------
    def allow(self, key: str) -> bool:
        """Return True if the probe for ``key`` may run right now."""
        if _env_disabled():
            return True
        rec = self._state.get(key)
        if rec is None or rec.opened_at is None:
            return True
        # Open -- check whether cooldown has elapsed.
        if self._clock() - rec.opened_at >= self._cooldown:
            # Transition to half-open by clearing opened_at but
            # keeping the failure counter at threshold so the next
            # failure re-opens cleanly without needing more misses.
            rec.opened_at = None
            return True
        return False

    def record_success(self, key: str) -> None:
        """Reset the failure counter and close the breaker for ``key``."""
        rec = self._state.get(key)
        if rec is None:
            self._state[key] = BreakerRecord(
                last_success_at=self._clock(),
            )
            return
        rec.consecutive_failures = 0
        rec.opened_at = None
        rec.last_error = None
        rec.last_success_at = self._clock()

    def record_failure(self, key: str, *, error: str | None = None) -> None:
        """Increment the failure counter for ``key`` and open the
        breaker if the threshold is met. ``error`` is stashed so
        ``describe_open`` can surface it."""
        now = self._clock()
        rec = self._state.get(key)
        if rec is None:
            rec = BreakerRecord()
            self._state[key] = rec
        rec.consecutive_failures += 1
        rec.last_failure_at = now
        if error is not None:
            rec.last_error = str(error)[:400]
        if rec.consecutive_failures >= self._threshold and rec.opened_at is None:
            rec.opened_at = now

    def describe_open(self, key: str) -> str | None:
        """Return a compact 'why' string for an open breaker or
        ``None`` when the breaker for ``key`` is currently closed.
        Format tuned for audit / probe payloads:
            "circuit-breaker open (3 consecutive failures, cools down
             in 45s; last error: timeout after 1.5s)"
        """
        if _env_disabled():
            return None
        rec = self._state.get(key)
        if rec is None or rec.opened_at is None:
            return None
        elapsed = self._clock() - rec.opened_at
        remaining = max(0.0, self._cooldown - elapsed)
        parts = [
            f"circuit-breaker open ({rec.consecutive_failures} consecutive "
            f"failures, cools down in {remaining:.0f}s"
        ]
        if rec.last_error:
            parts.append(f"; last error: {rec.last_error}")
        parts.append(")")
        return "".join(parts)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a JSON-safe view of the entire breaker state so
        operators can see it via ``/v1/tunnels/probe`` (v4.8.0 adds
        a ``breaker`` field to the response) or a future admin
        endpoint. Never returns internal object references."""
        now = self._clock()
        out: dict[str, dict[str, Any]] = {}
        for key, rec in self._state.items():
            open_ = rec.opened_at is not None
            entry: dict[str, Any] = {
                "state": "open" if open_ else "closed",
                "consecutive_failures": rec.consecutive_failures,
                "last_error": rec.last_error,
            }
            if open_ and rec.opened_at is not None:
                entry["cools_down_in_sec"] = round(
                    max(0.0, self._cooldown - (now - rec.opened_at)), 3
                )
            out[key] = entry
        return out

    def reset(self, key: str | None = None) -> None:
        """Clear one key or the entire state. Not called by
        production code; provided for the ``/v1/tunnels/probe?reset=1``
        knob and for tests."""
        if key is None:
            self._state.clear()
        else:
            self._state.pop(key, None)

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def cooldown(self) -> float:
        return self._cooldown


# ---------------------------------------------------------------------------
# Module-level singleton -- tunnels_probe shares one breaker across all
# invocations so the counters actually accumulate. Tests can either
# instantiate ``TunnelsBreaker`` directly (preferred) or call
# ``get_default_breaker().reset()`` between cases.
# ---------------------------------------------------------------------------
_DEFAULT: TunnelsBreaker | None = None


def summarize_snapshot(snapshot: dict[str, dict]) -> dict:
    """Compact per-provider view of a breaker snapshot (v4.16.0).

    Turns the raw ``{key: record}`` dict into a shape that answers
    the two questions an agent bootstrap actually cares about:

    1. Which providers should I deprioritise on this dial?
       (any provider with an ``open`` breaker anywhere)
    2. Which providers are trending bad?
       (any ``closed`` record with ``consecutive_failures > 0``)

    The key format is ``"{provider}|{host}:{port}"`` so multiple
    endpoints of the same provider (e.g. a Cloudflared reissue that
    moved the URL) collapse to one provider name in the summary.

    Returns:
      {
        "open":       ["cloudflared"],   # deduped, sorted, sorted
        "warn":       ["zerotier"],      # closed but failing
        "closed_ok":  ["tailscale"],     # closed, 0 failures
        "total_records": 3,
        "open_count": 1,
        "warn_count": 1,
      }
    """
    open_providers: set[str] = set()
    warn_providers: set[str] = set()
    closed_ok_providers: set[str] = set()
    for key, rec in snapshot.items():
        provider = str(key).split("|", 1)[0]
        state = rec.get("state") if isinstance(rec, dict) else None
        fails = 0
        if isinstance(rec, dict):
            raw = rec.get("consecutive_failures", 0)
            fails = int(raw) if isinstance(raw, int) else 0
        if state == "open":
            open_providers.add(provider)
        elif fails > 0:
            warn_providers.add(provider)
        else:
            closed_ok_providers.add(provider)
    # A provider that is open on ANY endpoint dominates over warn /
    # closed_ok on another endpoint of the same provider -- the
    # agent should treat it as deprioritised.
    warn_providers -= open_providers
    closed_ok_providers -= open_providers
    closed_ok_providers -= warn_providers
    return {
        "open": sorted(open_providers),
        "warn": sorted(warn_providers),
        "closed_ok": sorted(closed_ok_providers),
        "total_records": len(snapshot),
        "open_count": len(open_providers),
        "warn_count": len(warn_providers),
    }


def get_default_breaker() -> TunnelsBreaker:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = TunnelsBreaker()
    return _DEFAULT


def reset_default_breaker() -> None:
    """Test helper: throw away the module-level singleton so the
    next call to :func:`get_default_breaker` picks up fresh env
    overrides (used by env-driven tests)."""
    global _DEFAULT
    _DEFAULT = None


__all__ = [
    "TunnelsBreaker",
    "BreakerRecord",
    "get_default_breaker",
    "reset_default_breaker",
    "summarize_snapshot",
]
