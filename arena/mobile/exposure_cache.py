"""Last known public-tunnel exposure, cheap enough for `/v1/version` (#54).

`/v1/version` published `loopback_only` computed from the bind address
alone. With a Tailscale Funnel up, the bridge answered
``loopback_only: true`` **to a request that had arrived through the
funnel** -- the response body refuted itself, and the Android status
screen told the operator "Direct access from other machines: no" about a
bridge that was serving the public internet.

The honest answer needs the tunnel state, and `/v1/version` is
unauthenticated, so it must not shell out: `tailscale funnel status`
costs ~20 ms per call on the live bridge, which is a denial-of-service
lever for anyone who can reach the port. So the authenticated paths that
already pay for a snapshot publish what they learned here, and
`/v1/version` reads the memo.

Two rules make the memo safe to trust:

* **It expires.** A stale "a funnel was up" is a lie the moment the
  funnel stops, so an entry older than ``EXPOSURE_TTL_S`` is discarded
  and the answer becomes "unknown" rather than a confident stale one.
* **Unknown is not false.** ``exposed_publicly`` is a tri-state. Nobody
  has looked yet and "nothing is exposed" are different facts, and
  collapsing them is exactly the failure this module exists to fix --
  the same reason ``BridgeProbe.loopbackOnly()`` returns ``null``
  instead of ``false`` for a bridge too old to answer.
"""
from __future__ import annotations

import threading
import time
from typing import Any

# A funnel that went down more than a minute ago should not still be
# reported as up; a funnel that is up is re-observed by any authenticated
# status call. Short enough that the window of a stale "yes" is small,
# long enough that a phone polling /v1/version does not miss every memo.
EXPOSURE_TTL_S = 60.0

_LOCK = threading.Lock()


def _blank() -> dict[str, Any]:
    """The "nothing observed yet" state, in one place.

    Used both for the initial value and by ``reset``, so the two can
    never drift apart and leave a half-cleared memo behind.
    """
    return {"at": 0.0, "exposed": None, "providers": ()}


_UNKNOWN: dict[str, Any] = {"exposed": None, "providers": (), "age_s": None}

_STATE: dict[str, Any] = _blank()


def _public_providers(tunnels: dict[str, Any] | None) -> tuple[str, ...]:
    """Names of providers currently forwarding from outside this host.

    Mirrors how ``access_info.describe`` decides a tunnel counts: a URL
    plus either ``active`` or ``connected``. A provider that merely
    exists, or is installed but idle, is not exposure.
    """
    if not isinstance(tunnels, dict):
        return ()
    names: list[str] = []
    for name, snap in tunnels.items():
        if not isinstance(snap, dict):
            continue
        if not snap.get("public_url"):
            continue
        if snap.get("active") or snap.get("connected"):
            names.append(str(name))
    return tuple(sorted(names))


def record_tunnel_snapshot(tunnels: dict[str, Any] | None) -> None:
    """Remember what an authenticated caller just paid to find out."""
    providers = _public_providers(tunnels)
    with _LOCK:
        _STATE["at"] = time.monotonic()
        _STATE["exposed"] = bool(providers)
        _STATE["providers"] = providers


def exposure_snapshot(*, now: float | None = None) -> dict[str, Any]:
    """Return the memo, or an explicit unknown when it has expired.

    ``exposed`` is ``True``/``False``/``None``; ``age_s`` is ``None``
    when there is nothing to age.
    """
    stamp = time.monotonic() if now is None else now
    with _LOCK:
        at = float(_STATE["at"])
        exposed = _STATE["exposed"]
        providers = tuple(_STATE["providers"])
    if exposed is None:
        # `exposed` is the only sentinel: it is set to a bool and back to
        # None under the same lock as `at`, so it cannot disagree with it.
        return dict(_UNKNOWN)
    age = stamp - at
    if age > EXPOSURE_TTL_S or age < 0.0:
        # A negative age means the clock moved under us; treat it the
        # same as stale rather than reporting a fact from the future.
        return dict(_UNKNOWN)
    return {"exposed": exposed, "providers": providers, "age_s": age}


def reset() -> None:
    """Forget everything. For tests and for a clean process start."""
    with _LOCK:
        _STATE.clear()
        _STATE.update(_blank())
