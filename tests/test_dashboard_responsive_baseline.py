"""Baseline guards for the mobile-first Dashboard layer (v3.87.0).

Prevents silent regressions of the responsive CSS. If someone
inadvertently deletes the bottom-nav rules, the safe-area padding, or
the >=16px form-control font-size on mobile, this test fails loudly.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
CSS_RESPONSIVE = DASHBOARD / "assets" / "responsive.css"
CSS_BASE = DASHBOARD / "assets" / "dashboard.css"
INDEX = DASHBOARD / "index.html"


def test_responsive_css_exists():
    assert CSS_RESPONSIVE.is_file(), f"missing {CSS_RESPONSIVE}"
    assert CSS_RESPONSIVE.stat().st_size > 500, "responsive.css is suspiciously small"


def test_responsive_css_declares_expected_rules():
    text = CSS_RESPONSIVE.read_text(encoding="utf-8")
    required_snippets = [
        # narrow-viewport media query
        r"@media\s*\(\s*max-width:\s*900px\s*\)",
        # bottom-nav pattern: sidebar becomes fixed at bottom
        r"\.sidebar\s*{[^}]*position:\s*fixed",
        # safe-area for iPhone home indicator
        r"env\(safe-area-inset-bottom",
        # form controls at 16px minimum to defeat iOS auto-zoom
        r"input,\s*textarea,\s*select\s*{[^}]*font-size:\s*16px",
        # tables get horizontal scroll on mobile by default
        r"\.main\s+table:not\(\.responsive\)",
        # coarse-pointer 44px min touch target
        r"\(hover:\s*none\)\s+and\s+\(pointer:\s*coarse\)",
        r"min-height:\s*44px",
    ]
    for pattern in required_snippets:
        assert re.search(pattern, text, re.DOTALL), (
            f"responsive.css missing rule matching: {pattern}"
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
    # viewport-fit=cover is required for env(safe-area-inset-*) to work
    # on iPhones with a notch / home indicator.
    assert "viewport-fit=cover" in text, (
        "index.html viewport meta must include viewport-fit=cover to "
        "enable env(safe-area-inset-*)"
    )
    assert "width=device-width" in text
    assert "theme-color" in text, "index.html should set a theme-color meta"


def test_base_css_no_longer_owns_responsive_rules():
    """Guard against double-definitions after the split.

    Every @media rule now lives in responsive.css. The base file
    should be layout-agnostic.
    """
    text = CSS_BASE.read_text(encoding="utf-8")
    assert "@media" not in text, (
        "dashboard.css must not contain @media rules -- they belong "
        "in responsive.css so we have one source of truth for the "
        "mobile layer"
    )
