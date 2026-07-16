"""Guard: Doctor and Full Inventory tabs must render from the same
shared card renderers, not from two drifting copies.

This test enforces that:
    * ``dashboard/assets/03b-hw-cards.js`` exists and declares each
      ``_hwRender*`` function ONCE.
    * ``15b-doctor-hardware.js`` does NOT redefine any of them.
    * ``22-full-inventory-loader.js`` REFERENCES the shared renderers
      instead of shipping its own copy.
    * ``dashboard/index.html`` loads 03b BEFORE 15b and 22 so the
      symbols are ready when the loaders run.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dashboard" / "assets"
INDEX = ROOT / "dashboard" / "index.html"

# Renderers that MUST live in 03b-hw-cards.js only.
SHARED_RENDERERS = [
    "_hwCard", "_hwEsc", "_hwEl", "_hwFmtGB", "_hwFmtSeconds",
    "_hwRenderCPU", "_hwRenderMemory", "_hwRenderGPU", "_hwRenderDisks",
    "_hwRenderOS", "_hwRenderMotherboard", "_hwRenderNetwork",
    "_hwRenderThermal", "_hwRenderFans", "_hwRenderBattery",
    "_hwRenderAudio", "_hwRenderSmart", "_hwRenderTopProcesses",
    "_hwRenderListeningPorts", "_hwRenderSystemdFailed", "_hwRenderBoot",
    "_hwRenderServices", "_hwRenderExtra",
]


def test_shared_hw_cards_file_exists():
    p = ASSETS / "03b-hw-cards.js"
    assert p.is_file(), f"missing {p}"
    assert p.stat().st_size > 4000, "03b-hw-cards.js suspiciously small"


def test_all_shared_renderers_defined_in_03b():
    src = (ASSETS / "03b-hw-cards.js").read_text(encoding="utf-8")
    for name in SHARED_RENDERERS:
        assert re.search(rf"function\s+{re.escape(name)}\s*\(", src), (
            f"03b-hw-cards.js does not declare function {name}"
        )


def test_15b_doctor_hardware_does_not_redefine_renderers():
    src = (ASSETS / "15b-doctor-hardware.js").read_text(encoding="utf-8")
    duplicates = []
    for name in SHARED_RENDERERS:
        if re.search(rf"function\s+{re.escape(name)}\s*\(", src):
            duplicates.append(name)
    assert not duplicates, (
        "15b-doctor-hardware.js redefines shared renderers that live in "
        "03b-hw-cards.js. Delete the duplicates so Doctor and Full "
        "Inventory stay in sync.\n" + "\n".join(duplicates)
    )


def test_22_full_inventory_uses_shared_renderers():
    """v3.89.0: 22-full-inventory-loader.js delegates all card
    rendering to the unified _hwRenderAll() in 03b-hw-cards.js
    instead of hand-listing every renderer."""
    src = (ASSETS / "22-full-inventory-loader.js").read_text(encoding="utf-8")
    assert "_hwRenderAll" in src, (
        "22-full-inventory-loader.js must call the unified "
        "_hwRenderAll() helper from 03b-hw-cards.js."
    )
    # And it must NOT enumerate individual renderers by hand.
    for name in ("_hwRenderCPU(", "_hwRenderMemory(",
                 "_hwRenderThermal(", "_hwRenderTopProcesses("):
        assert name not in src, (
            f"22-full-inventory-loader.js still calls {name} directly. "
            "Route it through _hwRenderAll instead so Doctor + Full "
            "Inventory stay in sync automatically."
        )


def test_index_html_loads_03b_before_15b_and_22():
    text = INDEX.read_text(encoding="utf-8")
    idx_03b = text.find("03b-hw-cards.js")
    idx_15b = text.find("15b-doctor-hardware.js")
    idx_22 = text.find("22-full-inventory-loader.js")
    assert idx_03b > 0, "index.html does not link 03b-hw-cards.js"
    assert idx_15b > idx_03b, "15b must be loaded AFTER 03b"
    assert idx_22 > idx_03b, "22 must be loaded AFTER 03b"


def test_new_v883_renderers_present():
    src = (ASSETS / "03b-hw-cards.js").read_text(encoding="utf-8")
    for name in ("_hwRenderContainers", "_hwRenderSystemdTimers",
                 "_hwRenderNetworkIO", "_hwRenderUpdates",
                 "_hwRenderLoggedUsers", "_hwRenderCpuVulns",
                 "_hwRenderKernelModules"):
        assert re.search(rf"function\s+{re.escape(name)}\s*\(", src), (
            f"03b-hw-cards.js missing v3.88.3 renderer {name}"
        )
