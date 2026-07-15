"""Guard against inline hex/rgba colors in Dashboard HTML/JS assets.

The dashboard palette lives in a single place: ``dashboard/assets/dashboard.css``.
Every other file must reference colors via ``var(--foo)`` so dark mode
(and any future theme swap) stays consistent.

This test scans ``dashboard/assets/*.{html,js}`` for inline color-ish
declarations and fails if it finds any hex or rgb/rgba literal outside of
the CSS file itself.

Whitelist rules
---------------
* ``dashboard.css`` — the source of truth, exempt entirely.
* Files listed in ``ALLOWED_FILES`` — legacy pages we haven't cleaned yet.
  This set must not grow. Prefer moving colors into CSS vars.
* URLs that happen to contain ``#`` fragments are ignored because we only
  match on CSS property syntax (``color:``, ``background:``, ...).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dashboard" / "assets"

# Never allow new entries here without a clear reason and a CSS-var followup.
ALLOWED_FILES: set[str] = set()

# CSS declaration containing a hex or rgb/rgba color literal.
COLOR_RE = re.compile(
    r"(?:color|background(?:-color)?|border(?:-color)?|fill|stroke)"
    r"\s*:\s*(?:#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))"
)


def _scan(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    matches: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in COLOR_RE.finditer(line):
            matches.append(f"{path.name}:{lineno}: {m.group(0)}")
    return matches


def test_no_hardcoded_theme_colors_in_dashboard_assets():
    assert ASSETS.is_dir(), f"missing {ASSETS}"
    offenders: list[str] = []
    for path in sorted(ASSETS.iterdir()):
        if not path.is_file():
            continue
        if path.suffix not in {".html", ".js"}:
            continue
        if path.name in ALLOWED_FILES:
            continue
        offenders.extend(_scan(path))
    assert not offenders, (
        "Dashboard assets contain hardcoded colors. Move them into "
        "dashboard.css as CSS variables and reference via var(--foo).\n"
        + "\n".join(offenders)
    )
