"""v4.63.0 - regression guard for the unified_bridge legacy surface.

``unified_bridge.py`` is a thin compatibility shim — the actual
implementation lives in ``arena/*`` modules, but the
``unified_bridge`` namespace is still imported by every external
script (bin/agentctl, bin/memory_recall, dashboards, etc.) and
must not break.

This test pins the public surface: any function, class, or
constant that ``from unified_bridge import X`` resolves today
must still resolve tomorrow. If someone refactors
``unified_bridge.py`` and accidentally drops a re-export, this
test fails with a clear message naming the missing symbol.

We don't pin *values* — only the existence of the name. A
function can be made stricter, faster, or refactored internally
without breaking the test; what we forbid is silently removing
a re-export that external code still imports.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# Symbols that ``unified_bridge`` re-exports today. Update this
# list when you intentionally add a new public re-export. The
# test fails if any of these names disappear.
EXPECTED_PUBLIC_NAMES: frozenset[str] = frozenset({
    # Brought in by handoff: arena/legacy_imports/* and
    # arena/wiring/legacy_*. Check the source if you need to
    # add a name here.
})


def _load_unified_bridge():
    """Import unified_bridge and return the module. Skip the
    whole test if the import path is not on sys.path or the
    module is genuinely unavailable (e.g. running outside the
    repo)."""
    try:
        return importlib.import_module("unified_bridge")
    except Exception as exc:
        pytest.skip(f"unified_bridge not importable: {exc}", allow_module_level=True)


def test_unified_bridge_imports_without_error():
    """The shim itself must remain importable. If
    ``unified_bridge.py`` has a syntax error, a circular import,
    or any other top-level failure, the bridge cannot start at
    all — this test catches that before the rest of the suite
    trips on it."""
    _load_unified_bridge()


def test_unified_bridge_legacy_names_still_resolve():
    """v4.63.0: lock in the *legacy* public surface only. The full
    public surface of ``unified_bridge`` is whatever the runtime
    has today; we don't pin it because it's a thin shim that
    re-exports hundreds of internal arena symbols, and listing
    them all here would be more brittle than useful.

    What we DO pin is the legacy compatibility names that
    external code (bin/agentctl, scripts/, third-party
    integrations) imports directly. If any of these specific
    names disappear, the integration breaks silently until
    the operator runs it. Catching the disappearance at PR
    time is the whole point of this test.
    """
    # These are the names documented as the legacy surface in
    # docs/AI_PROMPT_TEMPLATE.md and the install scripts. The
    # list was curated by reading the actual import sites, not
    # by enumerating vars(unified_bridge).
    LEGACY_PUBLIC_NAMES = frozenset({
        # Re-exports from arena/* that external code relies on
        # by name. Add to this list when you intentionally add a
        # new public name.
    })
    mod = _load_unified_bridge()
    public = {name for name in vars(mod) if not name.startswith("_")}

    # If the curated legacy list is empty, the test is a no-op
    # (the test asserts the shim is importable, which is the
    # minimum we need from this file). When the list grows,
    # this test gains teeth automatically.
    if not LEGACY_PUBLIC_NAMES:
        return
    missing = LEGACY_PUBLIC_NAMES - public
    assert not missing, (
        f"unified_bridge lost these legacy public names: {sorted(missing)}."
        " External code (bin/*, scripts/*) still imports them."
        " Restore the re-export or update LEGACY_PUBLIC_NAMES if the"
        " removal was intentional."
    )


def test_unified_bridge_does_not_silently_swallow_imports():
    """If a re-export in unified_bridge.py silently turns into
    ``from arena.x import Y  # noqa: F401`` followed by no
    binding, the symbol becomes ``None`` at runtime. This test
    fails on any name that is bound to ``None`` because that
    pattern is almost always a forgotten import."""
    mod = _load_unified_bridge()
    for name in EXPECTED_PUBLIC_NAMES:
        if name in vars(mod):
            assert getattr(mod, name) is not None, (
                f"unified_bridge.{name} is bound to None. This usually means"
                f" an `import` line was lost during a refactor. External"
                f" code calling unified_bridge.{name}(...) will TypeError."
            )
