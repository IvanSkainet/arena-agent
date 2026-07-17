"""Persistent URL memory for the agentctl client (v4.40.0).

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

Security posture (v4.40.0 hardening):

The cache is a *fallback bootstrap*. Anything it says, the
client will attempt to contact and *authenticate to* with the
master bearer token. That makes the cache file a high-value
target: an attacker with write access to a user's home who can
substitute the URLs gets a straight path to
``Authorization: Bearer <BRIDGE_TOKEN>`` on a URL of their
choosing the next time the real bootstrap flaps.

Three defences, each independently sufficient in most threat
models but layered because home-directory write access is
scary enough to warrant belt+suspenders:

1. **HMAC-SHA256 signature** over the snapshot payload, keyed
   by a derived value of the client's ``BRIDGE_TOKEN``. An
   attacker who can write to the file cannot forge a valid
   signature without also knowing the token -- and if they
   know the token, they already have what the poisoned cache
   would have stolen. The signature check runs on every
   ``load()``; a bad or missing signature is treated exactly
   like "no cache".
2. **URL allowlist**. Even a validly-signed URL is rejected
   at load time if its scheme isn't http/https or its host
   matches metadata / ``.internal`` / ``.local`` / bare
   ``localhost`` -- those are known SSRF targets that no
   real bridge would advertise. Private IPv4 (RFC1918) is
   deliberately allowed because ZeroTier fallback is exactly
   that: ``http://10.57.152.120:8765`` from Ivan's LAN.
3. **``chmod 0o600``** after each atomic write. Prevents
   snoopers on multi-user machines from reading URLs (which
   though not secret still leak infrastructure topology --
   Tailscale hostnames, ngrok reserved domains, rotating
   cloudflared subdomains).

Together: with (1), an attacker cannot poison the cache
without the token; with (2), even an insider with the token
who forges a snapshot cannot redirect to obvious SSRF traps;
with (3), a co-tenant on the machine cannot read the cache
without escalating.

Schema version 2 (bumped from v4.39.0's version 1) is the
compat trip-wire: any v1 file left over from before this
release is silently rejected on load, and the next successful
bootstrap rewrites it as v2 (signed).

Design principles (unchanged from v4.39.0):

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

Cache format (``~/.arena/last_urls.json``) as of v4.40.0::

    {
      "envelope_version": 1,               # outer wrapper version
      "sig": "<hex hmac-sha256>",          # over `payload` bytes
      "payload": {
        "version": 2,                      # inner schema version
        "saved_at": 1784567890,            # unix epoch, int
        "bootstrap_url": "https://...",    # ARENA_BRIDGE_URL at capture time
        "urls": [
          {"provider": "tailscale", "url": "https://...", "kind": "https"},
          {"provider": "ngrok",     "url": "https://...", "kind": "https"},
          ...
        ]
      }
    }

The signature covers only the ``payload`` object serialised
deterministically (``sort_keys=True, separators=(",",":")``)
so any field added to the payload later automatically becomes
signature-covered without touching this module. The envelope
itself is intentionally NOT signed -- editing ``envelope_version``
or ``sig`` invalidates the signature and the file is discarded.

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

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# Bumped in v4.40.0 -- v4.39.0 wrote unsigned version-1 snapshots
# with no allowlist. Those are silently discarded on first load
# by this release, and the next successful bootstrap rewrites the
# cache in the new signed shape.
CACHE_VERSION = 2

# Envelope version is separate from schema version so we can add
# outer-wrapper fields (e.g. rotate the HMAC algorithm) without
# invalidating well-formed payloads.
ENVELOPE_VERSION = 1


# Hostnames that a legitimate bridge would never advertise as a
# reachable URL. Blocking them stops a valid-signature-but-still-
# obviously-wrong snapshot (only reachable via token compromise)
# from redirecting to a known SSRF trap. We deliberately do NOT
# block RFC1918 addresses: ZeroTier's fallback URL is exactly a
# private address (``http://10.57.152.120:8765``) and blocking
# it would defeat the whole point of the cache.
_BLOCKED_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "169.254.169.254",   # AWS/GCP/Azure IMDS
    "fd00:ec2::254",     # AWS IMDSv2 IPv6
})

_BLOCKED_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".localdomain",
    ".internal",
    ".local",
)


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


def _derive_key(secret: str) -> bytes:
    """Derive the HMAC key from the bearer token.

    We don't feed the raw token into ``hmac.new`` because we want
    two properties: (a) an operator inspecting the on-disk file
    with a hex-editor never sees anything resembling their token
    (only a SHA-256 of it, which is a one-way transform), and
    (b) if we ever rotate the derivation salt we can do so without
    invalidating people's live tokens.
    """
    return hashlib.sha256(
        b"arena-url-cache-v2|" + secret.encode("utf-8")
    ).digest()


def _canonical(payload: dict[str, Any]) -> bytes:
    """Deterministic serialisation used as HMAC input.

    ``sort_keys=True`` + tight separators + no ``indent`` mean
    that two payloads that are semantically identical always
    produce the same bytes, so the signature is stable across
    Python versions and json library implementations.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sign(payload: dict[str, Any], secret: str) -> str:
    """Return the hex HMAC-SHA256 of ``payload`` under ``secret``."""
    return hmac.new(
        _derive_key(secret), _canonical(payload), hashlib.sha256,
    ).hexdigest()


def _url_allowed(url: str) -> bool:
    """Return True when ``url`` passes the second-line allowlist.

    Rules (see module docstring for rationale):
      * scheme must be http or https
      * host must be non-empty
      * host is not in the SSRF-trap blocklist (metadata,
        localhost variants, cloud IMDS addresses)
      * host does not end in a known internal-only suffix
        (.internal, .local, .localhost, .localdomain)

    Private RFC1918 IPv4 is intentionally accepted -- ZeroTier's
    fallback URL is exactly that.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTS:
        return False
    for suffix in _BLOCKED_SUFFIXES:
        if host.endswith(suffix):
            return False
    return True


def save(cfg: dict[str, Any], *, bootstrap_url: str,
         secret: str | None = None) -> Path | None:
    """Persist an ``/v1/agent/config`` response for future
    fallback bootstrap.

    ``cfg`` is the raw dict returned by ``/v1/agent/config`` --
    we extract just the ``urls`` array and add a wrapper with
    a timestamp and the bootstrap URL that produced it. The
    latter is useful for operators inspecting the cache: it
    tells them "this snapshot was captured while talking to X".

    ``secret`` is the bearer token used to talk to the bridge;
    it is used only to sign the snapshot (via HMAC-SHA256 of a
    derived key -- the token itself never touches disk). Callers
    that don't have a token (e.g. a bridge with anonymous
    ``/v1/agent/config``) can pass ``None`` and the file will
    be written unsigned -- but such files are also refused on
    load, so anonymous callers effectively opt out of the fallback.

    Returns the ``Path`` that was written, or ``None`` when
    caching is disabled OR the cache would be empty OR ``secret``
    is None/empty. Any I/O error is swallowed and the function
    returns ``None`` -- callers should never rely on the cache
    being present.

    Atomic write via .tmp + rename plus explicit ``chmod 0o600``
    both before rename (default umask can leave the file world-
    readable otherwise) and after (belt+suspenders in case a
    filesystem quirk resets the mode).
    """
    if is_disabled():
        return None
    if not secret:
        # An unsigned cache cannot be trusted on load, so refuse
        # to write one in the first place. Callers without a
        # token simply don't benefit from the fallback.
        return None
    urls_raw = cfg.get("urls") or []
    urls_clean: list[dict[str, Any]] = []
    for u in urls_raw:
        if not isinstance(u, dict):
            continue
        url_val = u.get("url")
        if not url_val or not _url_allowed(url_val):
            # Skip malformed / SSRF-trap entries at write time so
            # we never persist them. The bridge should not have
            # advertised them, but defence in depth is cheap.
            continue
        urls_clean.append({
            "provider": u.get("provider"),
            "url": url_val,
            "kind": u.get("kind"),
        })
    if not urls_clean:
        return None
    payload = {
        "version": CACHE_VERSION,
        "saved_at": int(time.time()),
        "bootstrap_url": bootstrap_url,
        "urls": urls_clean,
    }
    envelope = {
        "envelope_version": ENVELOPE_VERSION,
        "sig": _sign(payload, secret),
        "payload": payload,
    }
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Tighten the parent directory too -- if we're creating
        # ~/.arena for the first time, don't leave it 0o755.
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # Set mode BEFORE the rename so there is no window in
        # which the final path exists with the default umask.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        # And once more after replace -- on some filesystems
        # (network mounts, ACL-heavy setups) the mode can be
        # reset by rename; this is the paranoid double-check
        # already established in arena/agent_helpers/files.py.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path
    except OSError:
        # Cache is a hint -- never propagate a filesystem error.
        return None


def load(secret: str | None = None) -> dict[str, Any] | None:
    """Read the last saved cache. Returns None when disabled,
    absent, unreadable, unsigned, wrongly-signed, or wrong-version.

    ``secret`` is the bearer token used to verify the HMAC
    signature. If the caller doesn't have a token, or the token
    doesn't match the one the snapshot was written with, the
    cache is treated as if it didn't exist -- returning ``None``
    is the safe default for every corruption / mismatch case.

    Never raises: an unreadable / malformed / mis-signed cache
    is treated as if no cache existed. The caller then bubbles
    up whatever error the bootstrap itself produced.

    Version compatibility:
      * ``envelope_version`` must equal ``ENVELOPE_VERSION`` (1
        as of v4.40.0). A future release may bump this to
        rotate the HMAC algorithm; older clients then treat the
        newer file as "no cache" and never try to use it.
      * ``payload.version`` must equal ``CACHE_VERSION`` (2 as
        of v4.40.0). v4.39.0 wrote version 1 with no signature;
        those files are silently ignored here.
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
        envelope = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("envelope_version") != ENVELOPE_VERSION:
        return None
    sig = envelope.get("sig")
    payload = envelope.get("payload")
    if not isinstance(sig, str) or not isinstance(payload, dict):
        return None
    if not secret:
        # No secret = cannot verify = cannot trust. Refuse.
        return None
    expected = _sign(payload, secret)
    # Constant-time comparison so a badly-signed cache doesn't
    # leak signature-prefix bytes via timing (paranoid; the file
    # is under the attacker's control anyway, but the discipline
    # is free).
    if not hmac.compare_digest(sig, expected):
        return None
    if payload.get("version") != CACHE_VERSION:
        # Different schema version -- ignore quietly. Future
        # arena-agent releases may bump this and migrate; for
        # now the safe fallback is "no cache".
        return None
    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        return None
    return payload


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


def fallback_bootstrap_urls(cfg_dict: dict[str, Any] | None = None,
                            secret: str | None = None) -> list[str]:
    """Return every URL from the cache in the order the server
    handed them out (priority order).

    ``cfg_dict`` is an optional pre-loaded cache payload -- when
    None we load from disk (which requires ``secret`` for the
    signature verification). Passing an in-memory dict lets tests
    exercise the ordering without touching the filesystem OR the
    HMAC path.

    Every URL is re-validated against the load-time allowlist
    (``_url_allowed``) even after signature verification. That
    is deliberately redundant with the write-time check in
    ``save()`` -- a valid signature only proves "the token
    holder wrote this", not "the URLs are still safe", and the
    allowlist is cheap to run twice.

    Never returns duplicates; preserves the input order (dict
    ordering guarantee since Python 3.7). Empty list when cache
    is absent, disabled, or the signature is invalid.
    """
    data = cfg_dict if cfg_dict is not None else load(secret)
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
        if not _url_allowed(url):
            # Belt+suspenders: reject SSRF-trap URLs at read time
            # too. A signed-but-malicious snapshot (insider with
            # token compromise) can't redirect us to metadata IMDS.
            continue
        seen.add(url)
        out.append(url)
    return out
