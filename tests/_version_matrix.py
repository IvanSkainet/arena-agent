"""Central version matrix for extension version-pin tests.

Historically each ``tests/test_extension_v4_*.py`` file kept its own
hard-coded tuple of accepted bridge/extension versions and every release
required editing 15+ tuples across 20 files by hand. That was error-prone
(v4.60.3 followup fixes remembered), and every mistake meant an extra
follow-up commit. This module centralises the accepted-version sets so
per-release maintenance touches exactly two constants (``LATEST_BRIDGE``,
``LATEST_EXT``) plus, if needed, the anchor date lists below.

Public surface
--------------
``BRIDGE_VERSIONS``
    Ordered tuple of bridge versions still allowed by regression tests.
    Older versions can be dropped once the release chain is stable enough
    that we no longer maintain the ``v4.5*`` test files.

``EXT_VERSIONS``
    Same idea for the browser chat extension (``chat_extension/``).

``LATEST_BRIDGE``
    Convenience alias for ``BRIDGE_VERSIONS[-1]`` — the version currently
    stamped in ``arena/constants.py`` and ``pyproject.toml``. The bump
    script in ``dev/bump_version.py`` keeps these in sync.

``LATEST_EXT``
    Same for the extension manifest.

Helper predicates
-----------------
``constants_snippets(prefix='VERSION')`` and
``pyproject_snippets(prefix='version')`` return the tuple of string
literals a test can search for in the raw source of ``constants.py`` /
``pyproject.toml`` respectively. This isolates the quoting style
(double-quoted, single-quoted) from the caller.
"""
from __future__ import annotations

from typing import Iterable, Tuple

# ---------------------------------------------------------------------------
# BRIDGE version chain — the value of ``arena.constants.VERSION``.
# Add a new entry per release; never renumber existing ones. Order is
# oldest first, latest last.
# ---------------------------------------------------------------------------
BRIDGE_VERSIONS: Tuple[str, ...] = (
    "4.51.3",
    "4.51.4",
    "4.52.0",
    "4.52.1",
    "4.52.2",
    "4.52.3",
    "4.52.4",
    "4.52.5",
    "4.52.6",
    "4.53.0",
    "4.53.1",
    "4.54.0",
    "4.54.1",
    "4.55.0",
    "4.55.1",
    "4.56.0",
    "4.57.0",
    "4.58.0",
    "4.59.0",
    "4.59.1",
    "4.60.0",
    "4.60.1",
    "4.60.2",
    "4.60.3",
    "4.60.4",
    "4.60.5",
    "4.60.6",
    "4.60.7",
    "4.60.8",
    "4.60.9",
    "4.60.10",
    "4.60.11",
    "4.60.12",
    "4.60.13",
    "4.60.14",
    "4.60.15",
    "4.60.16",
    "4.60.17",
    "4.60.18",
    "4.60.19",
    "4.60.20",
    "4.61.0",
    "4.61.1",
)

# ---------------------------------------------------------------------------
# EXTENSION version chain — value of chat_extension/manifest.json ["version"].
# The extension has been byte-identical since v4.53.1 (0.14.42), so this
# list rarely grows.
# ---------------------------------------------------------------------------
EXT_VERSIONS: Tuple[str, ...] = (
    "0.14.33",
    "0.14.34",
    "0.14.35",
    "0.14.36",
    "0.14.42",
)

LATEST_BRIDGE: str = BRIDGE_VERSIONS[-1]
LATEST_EXT: str = EXT_VERSIONS[-1]


def constants_snippets(prefix: str = "VERSION") -> Tuple[str, ...]:
    """String literals to grep for in ``arena/constants.py``.

    ``prefix`` defaults to ``VERSION`` (matches ``VERSION = "4.60.7"``).
    """
    return tuple(f'{prefix} = "{v}"' for v in BRIDGE_VERSIONS)


def pyproject_snippets(prefix: str = "version") -> Tuple[str, ...]:
    """String literals to grep for in ``pyproject.toml`` (``version = "…"``)."""
    return tuple(f'{prefix} = "{v}"' for v in BRIDGE_VERSIONS)


def any_bridge_in(text: str) -> bool:
    """True if ``text`` mentions ``VERSION = "<X.Y.Z>"`` for any accepted version."""
    return any(s in text for s in constants_snippets())


def any_pyproject_in(text: str) -> bool:
    """True if ``text`` mentions ``version = "<X.Y.Z>"`` for any accepted version."""
    return any(s in text for s in pyproject_snippets())


def any_ext_content_in(text: str) -> bool:
    """True if ``text`` contains the ``ARENA_CONTENT_SCRIPT_VERSION`` literal
    for any accepted extension version."""
    return any(f"ARENA_CONTENT_SCRIPT_VERSION = '{v}'" in text for v in EXT_VERSIONS)


def any_ext_return_in(text: str) -> bool:
    """True for ``insert_strategies.js`` — ``return '<X.Y.Z>';`` pattern."""
    return any(f"return '{v}';" in text for v in EXT_VERSIONS)


def any_ext_manifest_value(value: str) -> bool:
    """True if ``value`` is a currently-accepted extension manifest version."""
    return value in EXT_VERSIONS


def iter_bridge_versions() -> Iterable[str]:
    """Iterate over accepted bridge versions (oldest first)."""
    return iter(BRIDGE_VERSIONS)


__all__ = [
    "BRIDGE_VERSIONS",
    "EXT_VERSIONS",
    "LATEST_BRIDGE",
    "LATEST_EXT",
    "constants_snippets",
    "pyproject_snippets",
    "any_bridge_in",
    "any_pyproject_in",
    "any_ext_content_in",
    "any_ext_return_in",
    "any_ext_manifest_value",
    "iter_bridge_versions",
]
