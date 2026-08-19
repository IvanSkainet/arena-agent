"""Fail-closed navigation policy for every agent-driven browser navigation.

Why this module exists
----------------------
``browser_read`` takes ``validate_url`` as a keyword-**required** parameter,
so an SSRF check cannot be forgotten there: the call does not typecheck
without one. The CDP navigation path made the opposite choice — ``POST
/v1/browser/cdp/navigate`` checked only that ``url`` was non-empty and handed
the string to ``Page.navigate``. Both are authenticated, agent-reachable ways
to make *this host* retrieve a URL; only one was guarded (#103).

A browser driven over CDP is a fully capable HTTP client running on the host,
and ``Page.navigate`` accepts far more than ``https://``:

* ``http://127.0.0.1:8765/v1/...`` — the bridge's own API, and the CDP
  debugging port itself;
* ``http://169.254.169.254/latest/meta-data/`` — cloud instance metadata;
* ``http://192.168.0.1/`` — LAN devices reachable from the host but not from
  the caller;
* ``file:///etc/shadow`` — local files, whose contents are then readable
  through the extract/screenshot endpoints of the same subsystem.

``--remote-debugging-address=127.0.0.1`` protects the debugging *port*. It
says nothing about the *destinations* a navigation may reach.

Why the policy lives here and not in the handler
------------------------------------------------
Fifteen call sites reach ``navigate()``. Validating inside one handler is one
forgotten caller away from regressing — the argument ``arena/mobile/adb.py``
already makes for quoting inside ``run()`` rather than per-caller. So the
decision is made once, in ``check_navigation()``, and
``tests/test_cdp_navigation_policy.py`` enumerates the agent-facing entry
points by execution and requires each to refuse the same hostile URLs.

Why this is not just ``_validate_url``
--------------------------------------
Two reasons, both deliberate:

1. **Scheme coverage.** ``_validate_url`` is IP-focused and rejects anything
   that is not http/https, which is right for urllib but wrong as the only
   answer here: ``about:blank`` is the legitimate default for a new tab, and
   ``file:``/``data:``/``javascript:``/``chrome:``/``devtools:`` must be
   refused with an explanation rather than lumped in with them.

2. **TOCTOU honesty.** ``open_public_url`` closes the DNS-rebinding window
   for urllib by resolving once and pinning the validated IP for every hop
   (T62). That technique does not transfer: Chromium performs its own DNS
   resolution inside its network stack, and we cannot pin an address for it
   through ``Page.navigate``. A hostname that resolves public here may
   resolve to loopback microseconds later in the browser. This module
   therefore blocks literal and currently-resolving private addresses — which
   stops the whole class of casual and accidental cases — and does **not**
   claim to defeat an attacker who controls a DNS zone with a one-second TTL.
   Recording that limit is the honest engineering position; pretending the
   pinning carries over would be worse than leaving it unguarded, because it
   would be believed. See ``docs/`` note in SECURITY.md.

Local navigation is a legitimate operator workflow (driving a dashboard on
``127.0.0.1``, testing a local dev server), so it is available — but as an
explicit opt-in, ``ARENA_BROWSER_ALLOW_LOCAL_NAV=1``, never as the default.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from arena.security_ssrf import _validate_url

#: Navigation targets that carry no network or filesystem authority.
#: ``about:blank`` is the default a new tab is opened with, so refusing it
#: would break tab creation for no gain.
ALLOWED_OPAQUE_TARGETS = frozenset({"about:blank"})

#: Schemes a navigation may use once the target is not an opaque one above.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Opt-in that re-enables navigation to private/loopback addresses.
LOCAL_NAV_ENV = "ARENA_BROWSER_ALLOW_LOCAL_NAV"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


class NavigationRejected(ValueError):
    """A navigation target failed the policy. Message is caller-safe."""


def local_navigation_allowed(env: dict[str, str] | None = None) -> bool:
    """True when the operator opted into private-address navigation."""
    source = os.environ if env is None else env
    if LOCAL_NAV_ENV not in source:
        return False
    return source[LOCAL_NAV_ENV].strip().lower() in _TRUTHY


#: Verdicts from `_validate_url` that the local-navigation opt-in lifts.
#: A malformed address or an unparseable URL stays refused either way, so
#: pointing the operator at the opt-in for those would be misleading.
_OPT_IN_LIFTS = frozenset({
    "internal/metadata hostname not allowed",
    "private/internal address not allowed",
    "host resolves to a private/internal address",
})


def _private_target_error(url: str) -> str | None:
    """Reuse the audited SSRF validator, then explain a private verdict."""
    error = _validate_url(url)
    if error is None:
        return None
    if error in _OPT_IN_LIFTS:
        return f"{error}; navigation to private addresses requires {LOCAL_NAV_ENV}=1"
    return error


def check_navigation(url: object, *, env: dict[str, str] | None = None) -> str:
    """Return the URL to navigate to, or raise ``NavigationRejected``.

    Returning the value (rather than ``None`` on success) is deliberate: a
    caller that forgets to use the result keeps the unchecked string and the
    parity test catches it, instead of the guard silently becoming a no-op.
    """
    # An absent key and an empty string are the same operator mistake, and
    # callers already answered "missing 'url' parameter" for both before this
    # policy existed -- keep that wording so the error contract is unchanged.
    if url is None:
        raise NavigationRejected("missing 'url' parameter")
    if not isinstance(url, str):
        raise NavigationRejected("url must be a string")

    target = url.strip()
    if not target:
        raise NavigationRejected("missing 'url' parameter")

    if target.lower() in ALLOWED_OPAQUE_TARGETS:
        return target.lower()

    try:
        parsed = urlparse(target)
        scheme = parsed.scheme.lower()
        # `username`/`password` re-parse netloc lazily, so a malformed IPv6
        # literal raises here rather than above; read them inside the same
        # guarded block instead of parsing the URL a second time.
        has_credentials = parsed.username is not None or parsed.password is not None
    except ValueError as exc:
        raise NavigationRejected("invalid URL") from exc

    if scheme not in ALLOWED_SCHEMES:
        rendered = scheme or "<none>"
        raise NavigationRejected(
            f"URL scheme '{rendered}' not allowed for navigation "
            "(only http/https, or about:blank)"
        )

    # Userinfo is refused on every navigation, opt-in or not. `_validate_url`
    # tolerates it (urllib strips it before connecting), but a navigation
    # hands the credentials to Chromium, which caches them for the origin and
    # replays them on later requests the operator never authorised. The
    # public transport already rejects userinfo for the same reason; the
    # navigation path follows the stricter of the two.
    if has_credentials:
        raise NavigationRejected("credentials in URL are not allowed")

    if local_navigation_allowed(env):
        return target

    error = _private_target_error(target)
    if error:
        raise NavigationRejected(error)
    return target
