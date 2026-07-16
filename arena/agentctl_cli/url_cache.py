"""Persistent URL memory for the agentctl client (v4.39.0).

Problem statement (observed live during this session's Tailscale
outage): when the ``ARENA_BRIDGE_URL`` bootstrap URL becomes
unreachable (Tailscale TLS drops, cloudflared domain rotates,
laptop suspends), the agentctl client is completely cut off --
even though ``/v1/agent/config`` has been advertising three or
four working alternatives for weeks. We had them written down
in the bridge's response, but never persisted them on the
client side, so the moment the bootstrap died there was no
Plan B.

This module is that Plan B. It writes a small JSON snapshot to
``~/.arena/last_urls.json`` every time ``/v1/agent/config``
succeeds, and reads it back as a fallback bootstrap when the
primary URL times out.

Design principles:

* **Purely additive** -- when the cache is fresh, bootstrap
  works as before; nothing changes. When the cache is stale,
  fallback is silent and diagnostic (the result field records
  which URL served, so a user running ``bridge best --json``
  sees ``source: "cache-fallback"`` in the payload).
* **Client-side only** -- no server changes, no new endpoints.
  This is a hint the client keeps for itself.
* **User-controllable** -- a ``bridge cache`` subcommand lets
  operators inspect / clear it. An ``ARENA_BRIDGE_URL_CACHE=0``
  env variable disables it entirely for operators who prefer
  no local state.
* **Fail-soft** -- any I/O error reading or writing the cache
  is swallowed. The cache is a *hint*; missing it must never
  break a bridge call.

Cache format (``~/.arena/last_urls.json``)::

    {
      "version": 1,
      "saved_at": 1784567890,               # unix epoch, int
      "bootstrap_url": "https://...",       # ARENA_BRIDGE_URL at capture time
      "urls": [
        {"provider": "tailscale", "url": "https://...", "kind": "https"},
        {"provider": "ngrok",     "url": "https://...", "kind": "https"},
        ...
      ]
    }

Path convention:

* ``$ARENA_URL_CACHE_PATH`` env var, if set, wins (useful for
  tests and for operators who want the cache in a non-standard
  location).
* Otherwise ``~/.arena/last_urls.json``. The ``~/.arena``
  parent directory is created on first write.

Env variables:

* ``ARENA_BRIDGE_URL_CACHE`` -- ``0``/``false``/``no``/``off``
  disables both reads and writes. Anything else (or unset) =
  enabled. Case-insensitive.
* ``ARENA_URL_CACHE_PATH`` -- override the on-disk path.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


CACHE_VERSION = 1


def is_disabled() -> bool:
    """Return True when the operator has opted out via env var.

    The env variable is ``ARENA_BRIDGE_URL_CACHE``. Truthy-off
    values (case-insensitive): ``0``, ``false``, ``no``, ``off``.
    Anything else -- including unset -- means enabled.
    Deliberately asymmetric: cache is on by default because
    the problem it solves is "invisible failure when bootstrap
    dies". Making users opt in would leave the trap in place.
    """
    val = os.environ.get("ARENA_BRIDGE_URL_CACHE", "").strip().lower()
    return val in ("0", "false", "no", "off")


def cache_path() -> Path:
    """Return the on-disk cache path.

    Precedence:
      1. ``ARENA_URL_CACHE_PATH`` env variable (absolute path).
         Test suites use this to point at a tmp directory.
      2. ``~/.arena/last_urls.json`` otherwise.

    Does NOT create the parent directory -- that happens on
    first write via ``save()``.
    """
    override = os.environ.get("ARENA_URL_CACHE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".arena" / "last_urls.json"


def save(cfg: dict[str, Any], *, bootstrap_url: str) -> Path | None:
    """Persist an ``/v1/agent/config`` response for future
    fallback bootstrap.

    ``cfg`` is the raw dict returned by ``/v1/agent/config`` --
    we extract just the ``urls`` array and add a wrapper with
    a timestamp and the bootstrap URL that produced it. The
    latter is useful for operators inspecting the cache: it
    tells them "this snapshot was captured while talking to X".

    Returns the ``Path`` that was written, or ``None`` when
    caching is disabled OR the cache would be empty (no URLs
    to save -- writing an empty snapshot would confuse the
    reader into thinking there are no fallbacks). Any I/O error
    is swallowed and the function returns ``None`` -- callers
    should never rely on the cache being present.

    Atomic write via .tmp + rename so an interrupted save
    cannot leave a truncated JSON file that a future read
    trips on.
    """
    if is_disabled():
        return None
    urls_raw = cfg.get("urls") or []
    urls_clean = [
        {
            "provider": u.get("provider"),
            "url": u.get("url"),
            "kind": u.get("kind"),
        }
        for u in urls_raw
        if isinstance(u, dict) and u.get("url")
    ]
    if not urls_clean:
        return None
    payload = {
        "version": CACHE_VERSION,
        "saved_at": int(time.time()),
        "bootstrap_url": bootstrap_url,
        "urls": urls_clean,
    }
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path
    except OSError:
        # Cache is a hint -- never propagate a filesystem error.
        return None


def load() -> dict[str, Any] | None:
    """Read the last saved cache. Returns None when disabled,
    absent, or unreadable.

    Never raises: an unreadable / malformed cache is treated as
    if no cache existed. The caller then bubbles up whatever
    error the bootstrap itself produced.

    A "malformed" file (bad JSON, wrong schema version, missing
    required keys) is silently ignored rather than reported --
    stale caches from a future version of arena-agent shouldn't
    make older clients loud.
    """
    if is_disabled():
        return None
    path = cache_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != CACHE_VERSION:
        # Different schema version -- ignore quietly. Future
        # arena-agent releases may bump this and migrate; for
        # now the safe fallback is "no cache".
        return None
    urls = data.get("urls")
    if not isinstance(urls, list) or not urls:
        return None
    return data


def clear() -> bool:
    """Remove the cache file. Returns True when a file was
    actually removed, False when nothing was there -- same
    idempotent semantics as ``rm -f``. Respects the disable
    flag so ``ARENA_BRIDGE_URL_CACHE=0`` + ``clear`` is a
    no-op (there was nothing to clear anyway)."""
    if is_disabled():
        return False
    path = cache_path()
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def fallback_bootstrap_urls(cfg_dict: dict[str, Any] | None = None) -> list[str]:
    """Return every URL from the cache in the order the server
    handed them out (priority order).

    ``cfg_dict`` is an optional pre-loaded cache snapshot -- when
    None we load from disk. Passing an in-memory dict lets tests
    exercise the ordering without touching the filesystem.

    Never returns duplicates; preserves the input order (dict
    ordering guarantee since Python 3.7). Empty list when cache
    is absent or disabled.
    """
    data = cfg_dict if cfg_dict is not None else load()
    if not data:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for u in data.get("urls") or []:
        if not isinstance(u, dict):
            continue
        url = u.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
