"""Baseline guards for the mobile-first Dashboard layer.

Prevents silent regressions of the responsive CSS. If someone
inadvertently deletes the bottom-nav rules, the safe-area padding, or
the >=16px form-control font-size on mobile, this test fails loudly.

v3.87.1 additions:
    * badge must NOT get a 44px min-height (regression fixed)
    * shared renderMarkdown() must live in 03-helpers.js and be
      referenced from at least 22-full-inventory-loader.js and
      39-admin-update.js
    * base sheet must set min-width:0 on form controls so flex-items
      can shrink below their content width (fixes placeholder overflow)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
ASSETS = DASHBOARD / "assets"
CSS_RESPONSIVE = ASSETS / "responsive.css"
CSS_BASE = ASSETS / "dashboard.css"
INDEX = DASHBOARD / "index.html"
HELPERS = ASSETS / "03-helpers.js"


def test_responsive_css_exists():
    assert CSS_RESPONSIVE.is_file(), f"missing {CSS_RESPONSIVE}"
    assert CSS_RESPONSIVE.stat().st_size > 500, "responsive.css is suspiciously small"


def test_responsive_css_declares_expected_rules():
    text = CSS_RESPONSIVE.read_text(encoding="utf-8")
    required_snippets = [
        r"@media\s*\(\s*max-width:\s*900px\s*\)",
        r"\.sidebar\s*{[^}]*position:\s*fixed",
        r"env\(safe-area-inset-bottom",
        r"input,\s*textarea,\s*select\s*{[^}]*font-size:\s*16px",
        r"\.main\s+table:not\(\.responsive\)",
        r"\(hover:\s*none\)\s+and\s+\(pointer:\s*coarse\)",
        r"min-height:\s*44px",
    ]
    for pattern in required_snippets:
        assert re.search(pattern, text, re.DOTALL), (
            f"responsive.css missing rule matching: {pattern}"
        )


def test_badges_are_not_touch_targets():
    """Regression guard for v3.87.0 -- badges got 44px min-height and
    turned into tall empty green blocks with the label stuck to the
    top. Badges are inline status pills, not tap targets."""
    text = CSS_RESPONSIVE.read_text(encoding="utf-8")
    # Find the coarse-pointer block and verify .badge is NOT in it.
    match = re.search(
        r"@media\s*\(hover:\s*none\)\s+and\s+\(pointer:\s*coarse\)\s*{"
        r"([^{}]*(?:{[^{}]*}[^{}]*)*)}",
        text,
        re.DOTALL,
    )
    assert match, "coarse-pointer @media block not found"
    block = match.group(1)
    # Match .badge as a class token, not as a substring of e.g. .badge.sm
    assert not re.search(r"[^-\w]\.badge\s*[{,]", block + "{"), (
        "The coarse-pointer @media block still lists .badge as a "
        "touch target. Remove it -- badges are inline status pills.\n"
        + block
    )


def test_base_css_min_width_zero_on_inputs():
    """Without min-width:0 on flex items, inputs with long placeholders
    don't shrink and overflow their .row parent (visible on Terminal,
    Recall, Memory, Doctor, Settings, Control, Mobile tabs)."""
    text = CSS_BASE.read_text(encoding="utf-8")
    m = re.search(r"input,\s*textarea,\s*select\s*{([^}]+)}", text)
    assert m, "input,textarea,select rule missing from dashboard.css"
    rule = m.group(1)
    assert "min-width:0" in rule.replace(" ", ""), (
        "input,textarea,select must include min-width:0 so flex-items "
        "can shrink below their content width.\n" + rule
    )
    assert "max-width:100%" in rule.replace(" ", ""), (
        "input,textarea,select must include max-width:100% so no field "
        "escapes its container.\n" + rule
    )


def test_index_html_loads_responsive_css_after_base():
    text = INDEX.read_text(encoding="utf-8")
    idx_base = text.find("dashboard.css")
    idx_resp = text.find("responsive.css")
    assert idx_base >= 0, "index.html does not link dashboard.css"
    assert idx_resp >= 0, "index.html does not link responsive.css"
    assert idx_resp > idx_base, (
        "responsive.css must be loaded AFTER dashboard.css so its "
        "@media rules override the base layout"
    )


def test_index_html_declares_mobile_viewport():
    text = INDEX.read_text(encoding="utf-8")
    assert "viewport-fit=cover" in text
    assert "width=device-width" in text
    assert "theme-color" in text


def test_base_css_no_longer_owns_responsive_rules():
    text = CSS_BASE.read_text(encoding="utf-8")
    assert "@media" not in text, (
        "dashboard.css must not contain @media rules -- they belong "
        "in responsive.css so we have one source of truth for the "
        "mobile layer"
    )


def test_shared_markdown_renderer_lives_in_helpers():
    text = HELPERS.read_text(encoding="utf-8")
    assert "function renderMarkdown(" in text, (
        "renderMarkdown() must be defined in 03-helpers.js so every "
        "tab can use one renderer instead of copy-pasting."
    )
    # Its callers:
    inv = (ASSETS / "22-full-inventory-loader.js").read_text(encoding="utf-8")
    admin = (ASSETS / "39-admin-update.js").read_text(encoding="utf-8")
    assert "renderMarkdown(" in inv, (
        "22-full-inventory-loader.js must call renderMarkdown() so the "
        "Full Inventory output is human-readable, not raw text."
    )
    assert "renderMarkdown(" in admin, (
        "39-admin-update.js must call the shared renderMarkdown() "
        "instead of its own copy."
    )
