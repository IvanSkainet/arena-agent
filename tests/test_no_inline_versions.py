"""Guard against inline version literals in Dashboard HTML/JS.

The bridge version is served at runtime via ``window.ARENA_VERSION`` /
``{{VERSION}}`` template placeholder. Hardcoding ``v3.86.5`` (or any
semver literal) into UI labels, filenames, and comments creates stale
UI whenever we bump the version but forget to sweep the strings.

Rules
-----
* Match ``v?\\d+\\.\\d+\\.\\d+`` in ``dashboard/assets/*.{html,js}`` and
  in ``dashboard/index.html``.
* Allow ``{{VERSION}}``, ``ARENA_VERSION``, and semver *inside comments
  that are clearly changelog references* (kept minimal).

The point is: no cosmetic ``v2.9.0`` badges, no ``23-control-panel-v2-9-0.js``
filenames.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"

# Files we deliberately don't scan (typically the top-level index page
# that uses the {{VERSION}} placeholder in title/cache-bust).
# The index.html uses {{VERSION}} placeholder cache-busts intentionally.
# The other entries are legacy files that predate the guard. They will be
# renamed in a follow-up hygiene pass; do NOT expand this list without a
# clear plan to shrink it back.
ALLOWED_FILES: set[str] = {
    "index.html",
    # Legacy file whose *contents* also embed a hard-coded version banner
    # in a non-comment position; will be cleaned when the file is renamed.
    "05-terminal-v1-6-2-persistent-shell-like-se.js",
}

# Require the leading `v` so `127.0.0.1`, `192.168.1.5`, etc. don't match.
# Semver as a rendered version label ALWAYS looks like `v3.86.5`.
SEMVER_RE = re.compile(r"\bv\d+\.\d+\.\d+\b")

# Substrings that legitimize a semver literal on the same line.
CONTEXTUAL_ALLOWLIST = (
    "{{VERSION}}",
    "ARENA_VERSION",
    "window.ARENA_VERSION",
    "release/latest",  # release-notes anchor
    "no-store since ",  # rationale string in mirror error dialog
)

# Regex for lines that are pure comments (JS //, HTML <!--).
# The point of this test is to catch USER-VISIBLE version labels,
# not historical breadcrumbs in code comments that trace when a
# feature landed. Version drift in a comment is a docs problem;
# version drift in a rendered badge is a UX problem.
COMMENT_ONLY_RE = re.compile(r"^\s*(?://|/\*|\*|<!--|-->)")


def _scan(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        matches = SEMVER_RE.findall(raw)
        if not matches:
            continue
        if any(marker in raw for marker in CONTEXTUAL_ALLOWLIST):
            continue
        # Skip pure comments — see COMMENT_ONLY_RE docstring above.
        if COMMENT_ONLY_RE.match(raw):
            continue
        hits.append(f"{path.name}:{lineno}: {matches} :: {raw.strip()[:120]}")
    return hits


def test_no_inline_semver_literals():
    assert DASHBOARD.is_dir(), f"missing {DASHBOARD}"
    offenders: list[str] = []
    for root in (DASHBOARD, DASHBOARD / "assets"):
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            if path.name in ALLOWED_FILES:
                continue
            if path.suffix not in {".html", ".js"}:
                continue
            offenders.extend(_scan(path))
    assert not offenders, (
        "Dashboard files contain inline semver literals. Use "
        "{{VERSION}} / window.ARENA_VERSION instead.\n"
        + "\n".join(offenders)
    )


# Legacy filenames that embed a version — do not expand.
LEGACY_VERSIONED_FILENAMES: set[str] = {
    "05-terminal-v1-6-2-persistent-shell-like-se.js",
}


def test_no_versioned_asset_filenames():
    """Filenames like ``23-control-panel-v2-9-0.js`` are also forbidden.

    Legacy exceptions live in ``LEGACY_VERSIONED_FILENAMES``; the set must
    only shrink over time.
    """
    offenders: list[str] = []
    for path in sorted((DASHBOARD / "assets").iterdir()):
        if not path.is_file():
            continue
        if path.name in LEGACY_VERSIONED_FILENAMES:
            continue
        # matches -v1-2-3 / -v10-0-0 / -v2-9-0 etc.
        if re.search(r"-v\d+-\d+-\d+\b", path.stem):
            offenders.append(path.name)
    assert not offenders, (
        "Dashboard asset filenames must not embed version numbers. "
        "Rename these files (and update dashboard/index.html):\n"
        + "\n".join(offenders)
    )
