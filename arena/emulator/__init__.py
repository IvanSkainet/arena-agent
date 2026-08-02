"""Provider-agnostic Android emulator control.

Why this package exists
-----------------------
An earlier release shipped a ``mumu.*`` namespace: eight MCP tools welded to
one vendor's CLI (MuMu Player), on one OS (Windows), with an operator's home
directory baked into a default argument. That is the exact anti-pattern the
``core/build-capability`` skill warns about -- a tool that only works on the
machine it was written on teaches the agent nothing and dies with the host.

The replacement keeps only what is genuinely emulator-specific: *discovering*
which emulator managers exist on this host, *enumerating* their instances, and
*starting/stopping* them. Everything after boot -- shell, screenshot, tap,
install, logcat -- is plain ADB and already lives in the cross-platform
``arena.mobile`` domain, reachable through the ``mobile.*`` tools.

Providers are declared as data (:data:`BUILTIN_PROVIDERS`), not code, so adding
a manager is a table row rather than a new module. Hosts can declare their own
provider without touching this repository at all -- see
:func:`load_providers` and the ``ARENA_EMULATOR_PROVIDERS`` environment
variable.

Nothing here shells out through a shell: every invocation is an argv list.
"""
from __future__ import annotations

from arena.emulator.control import (
    attach,
    list_instances,
    providers_report,
    start,
    stop,
)
from arena.emulator.providers import (
    BUILTIN_PROVIDERS,
    EmulatorProvider,
    detect_providers,
    load_providers,
    resolve_binary,
)

__all__ = [
    "BUILTIN_PROVIDERS",
    "EmulatorProvider",
    "attach",
    "detect_providers",
    "list_instances",
    "load_providers",
    "providers_report",
    "resolve_binary",
    "start",
    "stop",
]
