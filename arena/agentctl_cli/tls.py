"""Shared TLS context helper for the agentctl CLI (v4.41.0).

Historical context
------------------
Before v4.41.0 both ``agentctl_common.py`` and ``agentctl_bridge.py``
each had their own private ``_ssl_context`` / ``_ssl_ctx`` helper
and both did the same thing::

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = 0

That is ``CERT_NONE`` — no hostname check, no certificate
validation. Any MITM on the path between the CLI and the bridge
could read and modify every request, including the
``Authorization: Bearer <BRIDGE_TOKEN>`` header. The audit that
surfaced the v4.39.0 cache-poisoning issue also flagged this,
under `#2 TLS verify` in ``SECURITY_AUDIT_v4.39.0.md``.

Threat model
------------
The bridge is reachable via three or four different URLs, each
with a different trust model:

* **Tailscale / cloudflared / ngrok**: real Let's Encrypt
  certificates issued for a stable hostname. Strict verify
  works flawlessly and is a hard security requirement — this
  is the path exposed to the public internet.
* **ZeroTier LAN**: ``http://10.57.152.120:8765``. Plain HTTP,
  never enters the TLS code path at all (``_ssl_context``
  returns ``None`` for non-``https`` URLs).
* **Loopback / self-signed bridge**: ``https://127.0.0.1:8765``
  with a self-signed cert (uncommon, but supported by
  ``arena/tls/`` for operators who terminate TLS on the bridge
  itself). Strict verify would fail here — we need an explicit
  opt-out.

Design
------
* **Verify strictly by default.** New behaviour in v4.41.0.
  Every ``https`` URL is validated against the system trust
  store with hostname checking. This is the change of default.
* **Opt-out via env var** ``ARENA_INSECURE_TLS`` (truthy
  values: ``1`` / ``true`` / ``yes`` / ``on``, case-insensitive).
  When set, the returned context has ``check_hostname=False``
  and ``verify_mode=CERT_NONE`` — same as pre-v4.41.0 behaviour.
* **Opt-out via CLI flag** ``--insecure``. Sets the env var
  for the current process before ``BRIDGE_TOKEN`` / any URL
  work happens. Handled in ``arena/cli.py`` at argv parse time
  so subcommands don't each have to plumb it.
* **Loud warning on opt-out.** When insecure mode is active,
  ``_warn_once_on_insecure()`` prints a single ``WARNING`` line
  to stderr the first time a TLS context is built in this
  process, so operators can never silently ship a script that
  disables verification. Repeated calls stay quiet.

Non-goals
---------
* Certificate pinning. Would tie the CLI to a specific bridge
  install; today the CLI is generic across bridges.
* Custom CA bundle path. ``ssl.create_default_context`` already
  honours ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` from the system
  environment. That is the standard way to point at a private
  CA; documenting it in ``bridge help`` is enough.
"""
from __future__ import annotations

import os
import ssl
import sys


# Truthy shapes for the opt-out env var. Deliberately narrow
# (only the four commonly-typed values) so a mistyped
# ``ARENA_INSECURE_TLS=please`` is a no-op rather than a silent
# security downgrade.
_INSECURE_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


# Guards ``_warn_once_on_insecure`` so the warning is emitted at
# most once per Python process. A pipeline that runs ``agentctl
# bridge best`` several times still sees the warning once, at
# the first call, and stays clean afterwards.
_INSECURE_WARNING_SHOWN: bool = False


def is_insecure_tls_enabled() -> bool:
    """Return True when the operator has opted out of TLS
    verification via ``ARENA_INSECURE_TLS``.

    Same truthy shapes the rest of the CLI uses:
    ``1``/``true``/``yes``/``on`` (case-insensitive). Anything
    else — including unset — means secure (default).

    Kept as a public function so
    ``tests/test_agentctl_tls.py`` can assert the resolution
    logic without touching the ssl module.
    """
    return (os.environ.get("ARENA_INSECURE_TLS", "").strip().lower()
            in _INSECURE_TRUTHY)


def _warn_once_on_insecure() -> None:
    """Print the "TLS verification disabled" warning once per
    process. Called every time a TLS context is built in
    insecure mode; the module-level guard makes it a no-op after
    the first call.

    Deliberately writes to stderr (not the logging framework)
    because agentctl runs as a plain CLI without logging
    configured, and we want the warning visible even in
    scripts that only capture stdout.
    """
    global _INSECURE_WARNING_SHOWN
    if _INSECURE_WARNING_SHOWN:
        return
    _INSECURE_WARNING_SHOWN = True
    print(
        "WARNING: TLS verification disabled (ARENA_INSECURE_TLS "
        "or --insecure). Traffic including the bearer token is "
        "vulnerable to MITM. Unset the flag as soon as you can.",
        file=sys.stderr,
    )


def build_ssl_context(url: str) -> ssl.SSLContext | None:
    """Return an ``ssl.SSLContext`` appropriate for ``url``, or
    ``None`` when the URL isn't ``https``.

    Behaviour matrix:

    +----------+----------------------------+----------------------------+
    | scheme   | ARENA_INSECURE_TLS unset   | ARENA_INSECURE_TLS truthy  |
    +==========+============================+============================+
    | http     | None                       | None                       |
    +----------+----------------------------+----------------------------+
    | https    | strict verify context      | insecure context + stderr  |
    |          | (system trust store,       | warning                    |
    |          | hostname checked)          |                            |
    +----------+----------------------------+----------------------------+

    ``None`` for HTTP is important: passing an SSLContext to
    ``urllib.request.urlopen`` on a plain HTTP URL is a subtle
    error that either raises or is silently ignored depending on
    Python version. Returning ``None`` matches the pre-v4.41.0
    convention every caller already handles.
    """
    if not url.startswith("https"):
        return None
    ctx = ssl.create_default_context()
    if is_insecure_tls_enabled():
        _warn_once_on_insecure()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    # else: leave the defaults from create_default_context in
    # place — check_hostname=True, verify_mode=CERT_REQUIRED.
    return ctx


def reset_warning_guard_for_tests() -> None:
    """Test-only hook so ``pytest`` can exercise the "warn
    exactly once per process" guarantee across multiple tests
    without spawning subprocesses. Not part of the public API;
    the underscore-free name is a hint that it is meant for
    ``tests/test_agentctl_tls.py`` only.
    """
    global _INSECURE_WARNING_SHOWN
    _INSECURE_WARNING_SHOWN = False
