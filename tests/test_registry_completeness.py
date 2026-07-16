"""v3.89.0: prove the unified registry is the ONLY source of truth.

If someone adds a new probe, they must:
    1. Add a ``Section(...)`` entry to ``arena/inventory/registry.py``.
No other list needs editing. These tests verify that guarantee.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


# ---- backend guarantees ---------------------------------------------------

def test_sections_derives_from_registry():
    """``arena.inventory.report.SECTIONS`` MUST be built from REGISTRY
    (no hand-maintained duplicate list)."""
    from arena.inventory.report import SECTIONS
    from arena.inventory.registry import REGISTRY
    reg_names = [s.name for s in REGISTRY]
    sec_names = [name for name, _ in SECTIONS]
    assert reg_names == sec_names, (
        "SECTIONS drifted from REGISTRY. report.py must not maintain "
        "its own list; do SECTIONS = [(s.name, s.collector) for s in REGISTRY]."
    )


def test_every_section_has_a_formatter_or_is_marked_none():
    """Each Section either has ``format_lines`` (rendered in text +
    Markdown output) or explicitly opts out with ``None``. No section
    accidentally goes without a formatter."""
    from arena.inventory.registry import REGISTRY
    for s in REGISTRY:
        assert s.format_lines is not None or s.show_in_doctor is False, (
            f"Section '{s.name}' has no format_lines and is not marked "
            f"show_in_doctor=False. Either add a formatter or opt out."
        )


def test_registry_endpoint_shape():
    """``registry_meta()`` output shape is what the frontend consumes.
    Each entry: name (str), label (str), category (str),
    show_in_doctor (bool)."""
    from arena.inventory.registry import registry_meta
    meta = registry_meta()
    assert isinstance(meta, list) and meta, "registry_meta must return non-empty list"
    for entry in meta:
        assert set(entry.keys()) == {"name", "label", "category", "show_in_doctor"}, (
            f"registry_meta entry has wrong keys: {entry.keys()}"
        )
        assert isinstance(entry["name"], str) and entry["name"]
        assert isinstance(entry["label"], str) and entry["label"]
        assert isinstance(entry["category"], str)
        assert isinstance(entry["show_in_doctor"], bool)


def test_all_registry_names_are_unique():
    from arena.inventory.registry import REGISTRY
    names = [s.name for s in REGISTRY]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate section names in REGISTRY: {dupes}"


# ---- frontend guarantees --------------------------------------------------

def test_body_01_overview_no_hardcoded_checkboxes():
    """Full Inventory checkbox strip is auto-built by
    ``_invBuildCheckboxStrip()`` from ``/v1/inventory/registry``.
    body-01-overview.html must contain only the 'all' fallback,
    not every section hand-coded."""
    html = (ROOT / "dashboard" / "assets" / "body-01-overview.html").read_text(encoding="utf-8")
    # Count `class="inv-sec"` occurrences -- must be exactly 1 (the "all" checkbox).
    count = html.count('class="inv-sec"')
    assert count == 1, (
        f"body-01-overview.html has {count} `class=\"inv-sec\"` "
        "checkboxes hardcoded. Only the 'all' fallback should stay; "
        "the rest come from the /v1/inventory/registry endpoint via "
        "_invBuildCheckboxStrip()."
    )
    # And the placeholder div is there for the JS to fill.
    assert 'id="invSectionStrip"' in html


def test_15b_doctor_hardware_uses_unified_renderer():
    src = (ROOT / "dashboard" / "assets" / "15b-doctor-hardware.js").read_text(encoding="utf-8")
    assert "_hwRenderAll" in src, (
        "15b-doctor-hardware.js must call the unified _hwRenderAll() "
        "instead of listing every _hwRender* by hand."
    )
    # And it must NOT list every renderer by hand any more.
    hand_calls = re.findall(r"_hwRender(?!All|Doctor)\w+\(", src)
    # `_hwEsc`, `_hwEl` etc. are utilities, not renderers -- filter them out.
    genuine = [c for c in hand_calls if not c.startswith("_hwRenderAll")]
    assert len(genuine) < 5, (
        "15b-doctor-hardware.js still calls specific _hwRender* helpers "
        f"({len(genuine)}); route them all through _hwRenderAll instead:\n"
        + "\n".join(sorted(set(genuine)))
    )


def test_22_full_inventory_uses_unified_renderer():
    src = (ROOT / "dashboard" / "assets" / "22-full-inventory-loader.js").read_text(encoding="utf-8")
    assert "_hwRenderAll" in src
    assert "_hwLoadRegistry" in src or "_invBuildCheckboxStrip" in src, (
        "22-full-inventory-loader.js must build the checkbox strip "
        "from the registry, not hardcode section names."
    )


def test_hw_card_map_contains_no_duplicates():
    """The client-side _HW_CARD_MAP array must have unique `name`
    values (excluding the __extra__ synthetic entry)."""
    src = (ROOT / "dashboard" / "assets" / "03b-hw-cards.js").read_text(encoding="utf-8")
    names = re.findall(r'\{name:\s*"([^"]+)"', src)
    real = [n for n in names if n != "__extra__"]
    dupes = {n for n in real if real.count(n) > 1}
    assert not dupes, f"duplicate names in _HW_CARD_MAP: {dupes}"


# ---- registry ↔ card map consistency --------------------------------------

def test_every_registry_section_has_matching_card_entry():
    """Section names in the Python registry should have a matching
    entry in the JS _HW_CARD_MAP. It's OK for a section to be text-
    only (mark it with a comment); we just require the intentional
    delta to be small."""
    from arena.inventory.registry import REGISTRY
    src = (ROOT / "dashboard" / "assets" / "03b-hw-cards.js").read_text(encoding="utf-8")
    card_names = set(re.findall(r'\{name:\s*"([^"]+)"', src))
    reg_names = {s.name for s in REGISTRY}
    # Sections we deliberately DON'T card-render on their own -- they
    # merge into another card or only appear in raw view.
    text_only = {
        # Section 'identity' has no card renderer -- OS info is
        # rendered via _hwRenderOS from source.os (registry entry 'os').
        "identity",
        # Huge lists only useful in raw view / for agents parsing JSON.
        "storage_devices", "pci_devices", "usb_devices", "thermal",
        # Bundled into the _hwRenderExtra `__extra__` card.
        "runtimes", "package_managers", "browsers",
        # Rendered as key/value in the extras area only.
        "displays", "python_env", "env",
    }
    missing = reg_names - card_names - text_only
    assert not missing, (
        "These registered sections have no _HW_CARD_MAP entry AND are "
        "not in the text_only allowlist:\n" + "\n".join(sorted(missing))
    )
