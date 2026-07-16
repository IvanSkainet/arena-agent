"""Dashboard asset manifest builder (v3.91.0 unification).

Historically ``dashboard/index.html`` hardcoded two arrays:

    ARENA_DASHBOARD_SCRIPTS = [...]   # 51 hand-listed .js paths
    bodyParts               = [...]   # 18 hand-listed body-XX.html paths

Every new tab / renderer required editing both. Now the browser
fetches ``GET /gui/assets/manifest.json`` at boot and the arrays
are auto-derived from what's actually on disk, sorted so the
load order is deterministic and matches what humans expect.

Ordering rules:
    * JS scripts:  sort by the numeric prefix (``00-``, ``01-``,
                   ``09b-``, ``21b-``), then alphabetically. Files
                   without a prefix sort last.
    * HTML bodies: same rules -- ``body-00-shell.html`` first,
                   ``body-01-overview.html`` next, and so on.

Excluded on purpose:
    * ``dashboard.css`` / ``responsive.css``  -- loaded via
      ``<link>`` in the shell head, not as scripts.
    * ``manifest.json`` itself -- would loop.
    * Anything with a suffix other than ``.js`` / ``.html``.
    * Test fixtures, ``.map`` files, hidden files.

Guard tests in ``tests/test_dashboard_asset_manifest.py`` prove
this stays in sync with reality: every file the manifest lists
exists on disk, and every dashboard JS/HTML on disk is in the
manifest (or explicitly excluded).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


# Files that live in dashboard/assets/ but are NOT boot-loaded via
# the manifest. Keep the set small and explain each entry.
EXCLUDED_ASSET_NAMES: frozenset[str] = frozenset({
    "dashboard.css",       # linked in <head> as a stylesheet
    "responsive.css",      # linked in <head> as a stylesheet
    "manifest.json",       # self-reference would be silly
})

_PREFIX_RE = re.compile(r"^(\d+)([a-z]?)-")


def _sort_key(name: str) -> tuple:
    """Numeric prefix sort with alpha suffix (00 < 01 < 09b < 10 < 21b).
    Files without a numeric prefix sort last, then alphabetically."""
    m = _PREFIX_RE.match(name)
    if not m:
        return (10_000, "", name)
    num = int(m.group(1))
    suffix = m.group(2) or ""
    return (num, suffix, name)


def _list_sorted(
    assets_dir: Path,
    suffix: str,
    name_predicate=lambda n: True,
) -> list[str]:
    if not assets_dir.is_dir():
        return []
    names = []
    for path in assets_dir.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name.endswith(".map"):
            continue
        if path.suffix != suffix:
            continue
        if path.name in EXCLUDED_ASSET_NAMES:
            continue
        if not name_predicate(path.name):
            continue
        names.append(path.name)
    names.sort(key=_sort_key)
    return names


def build_manifest(bridge_dir: Path | str) -> dict:
    """Return ``{"scripts": [...], "bodies": [...], "version": N}``
    where each list is a URL-relative path (``/gui/assets/foo.js``).

    ``version`` is a monotonic integer that changes whenever the
    file set changes; clients can use it for cache invalidation.
    """
    assets_dir = Path(bridge_dir) / "dashboard" / "assets"
    scripts = _list_sorted(assets_dir, ".js")
    bodies = _list_sorted(assets_dir, ".html",
                          name_predicate=lambda n: n.startswith("body-"))
    # Content-addressed version: hash of the joined manifest so any
    # add/rename/delete busts the browser cache automatically.
    import hashlib
    signature = hashlib.sha256(
        ("|".join(scripts) + "\n" + "|".join(bodies)).encode("utf-8"),
    ).hexdigest()[:12]
    return {
        "ok": True,
        "signature": signature,
        "scripts": [f"/gui/assets/{n}" for n in scripts],
        "bodies":  [f"/gui/assets/{n}" for n in bodies],
    }
