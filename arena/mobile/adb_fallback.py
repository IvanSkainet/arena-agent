"""Transport fallback for the arena.mobile ADB layer (v3.84.5).

The physical USB link between the bridge host and a phone can flap under
load -- long uiautomator dumps, active video recording, or a marginal
cable will regularly push a device into `offline` for a few seconds.
Every operation in `arena.mobile.*` funnels through `adb.run(..., serial=...)`,
so this module gives that call a chance to route around the failure by
transparently re-issuing it against a known-good alternative transport
(wireless ADB, typically `ip:5555`).

Design goals:

* **Zero surprise when no fallback is configured.** If a phone has never
  been probed for a wireless alias, the registry stays empty and every
  call flows through the original USB serial with no wrapper overhead.

* **Per-serial circuit breaker.** After `_MAX_CONSECUTIVE_FAILS` back-to-back
  offline-shaped errors on a transport, that transport is marked unhealthy
  for `_UNHEALTHY_COOLDOWN_SEC` seconds. During cooldown the router picks
  the next healthy transport for the same physical serial. When the whole
  set is unhealthy we still try the primary (best effort) so callers see
  the underlying error verbatim instead of a mysterious "no transport"
  message.

* **Aliases are one-way.** A transport alias identifies the same physical
  device (same phone serial) reachable via a different ADB address. The
  registry is keyed by the *canonical* serial (whatever the caller passed
  to `arena.mobile.handlers`); aliases live inside the record. Nothing
  outside this module needs to know the alias exists.

* **Thread-safe.** The registry is guarded by a single `RLock`. Every
  mutating helper takes it, every read produces a snapshot.

The wireless-ADB *pairing* / *tcpip* dance is handled by
`arena.mobile.wireless` -- this module only cares about routing an already-
connected transport.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# How many back-to-back offline-shaped errors mark a transport unhealthy.
_MAX_CONSECUTIVE_FAILS = 3

# How long a transport stays unhealthy after tripping the breaker.
_UNHEALTHY_COOLDOWN_SEC = 20.0

# Substrings in stderr / error messages that count as "device unreachable"
# for the purposes of tripping the breaker. Kept intentionally short so
# a genuine permission error doesn't accidentally fail over.
_OFFLINE_MARKERS = (
    "device offline",
    "no devices/emulators found",
    "device still authorizing",
    "device unauthorized",
    "failed to get feature set",
    "cannot connect to daemon",
    "no such device",
    "protocol fault",         # occasional adb server hiccup
    "server didn't ack",      # daemon restart in-flight
)

# Regex for the harder-to-classify "device ... not found" family, which
# comes in a few flavours (adb: device '2200ad3b' not found /
# adb: device not found / etc.). We keep it separate so it can't
# accidentally match an unrelated "activity not found" or "package not
# found" message from am/pm.
import re as _re
_OFFLINE_DEVICE_NOT_FOUND = _re.compile(r"\bdevice\b[^\n]{0,64}\bnot found\b",
                                        _re.IGNORECASE)


def _looks_offline(stderr: str, returncode: int) -> bool:
    if returncode == 0:
        return False
    lowered = (stderr or "").lower()
    if any(m in lowered for m in _OFFLINE_MARKERS):
        return True
    if _OFFLINE_DEVICE_NOT_FOUND.search(stderr or ""):
        return True
    return False


@dataclass
class TransportHealth:
    """Rolling health of a single transport address (e.g. `2200ad3b`
    or `192.168.50.181:5555`)."""

    address: str
    kind: str  # "usb" | "tcp"
    consecutive_fails: int = 0
    unhealthy_until: float = 0.0
    last_error: str = ""
    total_calls: int = 0
    total_fails: int = 0
    last_used_at: float = 0.0

    def is_healthy(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now >= self.unhealthy_until

    def record_success(self) -> None:
        self.total_calls += 1
        self.consecutive_fails = 0
        self.last_error = ""
        self.last_used_at = time.time()

    def record_failure(self, stderr: str) -> None:
        self.total_calls += 1
        self.total_fails += 1
        self.consecutive_fails += 1
        self.last_error = (stderr or "").strip()[:200]
        self.last_used_at = time.time()
        if self.consecutive_fails >= _MAX_CONSECUTIVE_FAILS:
            self.unhealthy_until = time.time() + _UNHEALTHY_COOLDOWN_SEC


@dataclass
class DeviceTransports:
    """Every known transport for one physical phone. `canonical` is the
    serial string the caller uses; `transports` is the ordered list of
    addresses to try when routing an ADB call."""

    canonical: str
    transports: list[TransportHealth] = field(default_factory=list)
    # Number of times the router had to fall back off `transports[0]`.
    failovers: int = 0
    # Timestamp of last successful call on any transport.
    last_success_at: float = 0.0


class TransportRegistry:
    """Thread-safe process-wide store. Instantiated once as `_REGISTRY`
    below; kept as a class so tests can spin up isolated copies."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, DeviceTransports] = {}

    # -- Registration ------------------------------------------------------

    def register(self, canonical: str, *, kind: str = "usb") -> DeviceTransports:
        """Idempotently register `canonical` as the primary transport
        for its own serial. Returns the resulting `DeviceTransports`."""
        with self._lock:
            dev = self._devices.get(canonical)
            if dev is None:
                dev = DeviceTransports(canonical=canonical)
                dev.transports.append(TransportHealth(address=canonical, kind=kind))
                self._devices[canonical] = dev
            return dev

    def add_alias(self, canonical: str, alias: str, *, kind: str = "tcp") -> None:
        """Attach a fallback transport (typically a `host:port` string
        from wireless ADB) to an existing device record. No-op if the
        alias is already known; primary is not touched."""
        with self._lock:
            dev = self.register(canonical)
            if alias == canonical:
                return
            if any(t.address == alias for t in dev.transports):
                return
            dev.transports.append(TransportHealth(address=alias, kind=kind))

    def drop_alias(self, canonical: str, alias: str) -> bool:
        with self._lock:
            dev = self._devices.get(canonical)
            if not dev:
                return False
            before = len(dev.transports)
            dev.transports = [t for t in dev.transports if t.address != alias]
            return len(dev.transports) != before

    # -- Routing -----------------------------------------------------------

    def pick_transport(self, canonical: str) -> str:
        """Return the transport address to use for the next ADB call.

        Never raises. When no aliases exist we return `canonical` so
        `adb.run` behaves exactly as before. When the primary is healthy
        we return it. When the primary is unhealthy but an alias is
        healthy we return the alias and bump the failover counter.
        When everything is unhealthy we still return the primary --
        the caller will see the real error and can act on it.
        """
        with self._lock:
            dev = self._devices.get(canonical)
            if dev is None or not dev.transports:
                return canonical
            now = time.time()
            healthy = [t for t in dev.transports if t.is_healthy(now)]
            if healthy:
                chosen = healthy[0]
                if chosen.address != dev.transports[0].address:
                    dev.failovers += 1
                return chosen.address
            # All unhealthy -- return the primary so the caller sees the
            # underlying failure surface.
            return dev.transports[0].address

    def record_outcome(self, canonical: str, address: str, *,
                       returncode: int, stderr: str) -> None:
        """Update transport health after an ADB call completes."""
        with self._lock:
            dev = self._devices.get(canonical)
            if not dev:
                return
            for t in dev.transports:
                if t.address == address:
                    if _looks_offline(stderr, returncode):
                        t.record_failure(stderr)
                    elif returncode == 0:
                        t.record_success()
                        dev.last_success_at = time.time()
                    else:
                        # Non-offline non-zero exit (e.g. app-level error).
                        # Bump total_calls but don't trip the breaker.
                        t.total_calls += 1
                        t.last_used_at = time.time()
                    return

    # -- Introspection -----------------------------------------------------

    def snapshot(self, canonical: str | None = None) -> list[dict[str, Any]]:
        """JSON-friendly dump of every known device (or one specifically)."""
        with self._lock:
            devs = ([self._devices[canonical]] if canonical and canonical in self._devices
                    else list(self._devices.values()))
            now = time.time()
            out: list[dict[str, Any]] = []
            for dev in devs:
                out.append({
                    "canonical": dev.canonical,
                    "failovers": dev.failovers,
                    "last_success_at": dev.last_success_at,
                    "transports": [
                        {
                            "address": t.address,
                            "kind": t.kind,
                            "healthy": t.is_healthy(now),
                            "consecutive_fails": t.consecutive_fails,
                            "cooldown_remaining_sec": max(0.0, t.unhealthy_until - now),
                            "total_calls": t.total_calls,
                            "total_fails": t.total_fails,
                            "last_error": t.last_error,
                            "last_used_at": t.last_used_at,
                        }
                        for t in dev.transports
                    ],
                })
            return out

    def reset(self, canonical: str | None = None) -> int:
        """Clear one device's registry entry (or everything). Returns
        the count of entries removed."""
        with self._lock:
            if canonical is None:
                n = len(self._devices)
                self._devices.clear()
                return n
            return 1 if self._devices.pop(canonical, None) else 0


# Process-wide default registry. Consumers should use this via the
# module-level helpers below; the class is public only for tests.
_REGISTRY = TransportRegistry()


def register(canonical: str) -> None:
    _REGISTRY.register(canonical)


def add_alias(canonical: str, alias: str, *, kind: str = "tcp") -> None:
    _REGISTRY.add_alias(canonical, alias, kind=kind)


def drop_alias(canonical: str, alias: str) -> bool:
    return _REGISTRY.drop_alias(canonical, alias)


def pick_transport(canonical: str) -> str:
    return _REGISTRY.pick_transport(canonical)


def record_outcome(canonical: str, address: str, *,
                   returncode: int, stderr: str) -> None:
    _REGISTRY.record_outcome(canonical, address,
                             returncode=returncode, stderr=stderr)


def snapshot(canonical: str | None = None) -> list[dict[str, Any]]:
    return _REGISTRY.snapshot(canonical)


def reset(canonical: str | None = None) -> int:
    return _REGISTRY.reset(canonical)


def looks_offline(stderr: str, returncode: int) -> bool:
    """Public export -- lets tests share the same classifier the
    circuit breaker uses."""
    return _looks_offline(stderr, returncode)
