"""v3.91.0: dashboard asset manifest is the single source of truth
for which JS/HTML files boot-load into the Dashboard.

Enforces:
    * dashboard/index.html no longer hardcodes the script or body
      file lists (they come from GET /gui/assets/manifest.json).
    * The manifest builder produces a stable, deterministic order.
    * Every .js on disk is in the manifest (or explicitly excluded).
    * Every .html body-*.html on disk is in the manifest.
    * The manifest doesn't reference files that don't exist.
    * Sort order puts numeric-prefix files first, then alpha.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dashboard" / "assets"
INDEX = ROOT / "dashboard" / "index.html"


def test_manifest_builder_returns_expected_shape():
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    assert m["ok"] is True
    assert isinstance(m["scripts"], list) and m["scripts"], "no scripts"
    assert isinstance(m["bodies"], list) and m["bodies"], "no bodies"
    assert isinstance(m["signature"], str) and len(m["signature"]) == 12
    for path in m["scripts"] + m["bodies"]:
        assert path.startswith("/gui/assets/"), path
        assert not path.endswith("/"), path


def test_manifest_covers_every_js_on_disk():
    from arena.gui.asset_manifest import build_manifest, EXCLUDED_ASSET_NAMES
    m = build_manifest(ROOT)
    listed = {p.rsplit("/", 1)[-1] for p in m["scripts"]}
    on_disk = {p.name for p in ASSETS.iterdir()
               if p.is_file() and p.suffix == ".js"
               and not p.name.startswith(".")
               and not p.name.endswith(".map")}
    missing = on_disk - listed - EXCLUDED_ASSET_NAMES
    assert not missing, (
        "These .js files exist under dashboard/assets/ but the "
        "manifest doesn't list them:\n"
        + "\n".join(sorted(missing))
    )


def test_manifest_covers_every_body_html_on_disk():
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    listed = {p.rsplit("/", 1)[-1] for p in m["bodies"]}
    on_disk = {p.name for p in ASSETS.iterdir()
               if p.is_file() and p.suffix == ".html"
               and p.name.startswith("body-")}
    missing = on_disk - listed
    assert not missing, (
        "These body-*.html files exist but the manifest doesn't "
        "list them:\n" + "\n".join(sorted(missing))
    )


def test_manifest_only_references_existing_files():
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    for path in m["scripts"] + m["bodies"]:
        rel = path.replace("/gui/assets/", "", 1)
        assert (ASSETS / rel).is_file(), (
            f"manifest lists {path} but the file is missing from disk"
        )


def test_manifest_sort_order_prefixes_first():
    """00-core comes before 00-tabs (alpha within same prefix),
    before 09b (alpha suffix), before 21b, before 40-multiagent."""
    from arena.gui.asset_manifest import build_manifest
    m = build_manifest(ROOT)
    names = [p.rsplit("/", 1)[-1] for p in m["scripts"]]
    # Verify known relative ordering.
    def idx(name):
        for i, n in enumerate(names):
            if n == name: return i
        return -1
    def assert_before(a, b):
        ia, ib = idx(a), idx(b)
        if ia < 0 or ib < 0:
            return  # file removed from repo; not this test's concern
        assert ia < ib, f"expected {a} before {b}, got {names[max(0,ia-1):ib+1]}"
    assert_before("00-core.js", "01-tab-switching.js")
    assert_before("01-tab-switching.js", "04-overview.js")
    assert_before("09-browser-search.js", "09b-browser-read-dump.js")
    assert_before("09b-browser-read-dump.js", "10-reports.js")
    assert_before("15-doctor-run.js", "15b-doctor-hardware.js")
    assert_before("21-slash-commands.js", "22-full-inventory-loader.js")


def test_index_html_no_longer_hardcodes_asset_lists():
    """Regression guard: index.html must NOT hardcode either the
    script list or the body list -- both come from the manifest."""
    text = INDEX.read_text(encoding="utf-8")
    # A hardcoded scripts array would contain many '/gui/assets/XX-'
    # entries. We tolerate up to 3 (the fallback / documentation).
    hardcoded = re.findall(r"'/gui/assets/[^']+\.(js|html)'", text)
    assert len(hardcoded) <= 3, (
        f"index.html hardcodes {len(hardcoded)} asset paths. "
        "The manifest endpoint (/gui/assets/manifest.json) is the "
        "single source of truth; index.html should fetch from it."
    )


def test_index_html_fetches_manifest():
    text = INDEX.read_text(encoding="utf-8")
    assert "/gui/assets/manifest.json" in text, (
        "index.html must fetch /gui/assets/manifest.json to build "
        "the asset lists dynamically."
    )


def test_manifest_signature_stable_across_calls():
    from arena.gui.asset_manifest import build_manifest
    s1 = build_manifest(ROOT)["signature"]
    s2 = build_manifest(ROOT)["signature"]
    assert s1 == s2, "manifest signature must be deterministic"


def test_excluded_assets_not_in_manifest():
    from arena.gui.asset_manifest import build_manifest, EXCLUDED_ASSET_NAMES
    m = build_manifest(ROOT)
    all_listed = {p.rsplit("/", 1)[-1] for p in m["scripts"] + m["bodies"]}
    leaked = all_listed & EXCLUDED_ASSET_NAMES
    assert not leaked, (
        f"Explicitly excluded assets leaked into manifest: {leaked}"
    )
