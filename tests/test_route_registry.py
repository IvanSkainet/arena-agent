"""v3.90.0: guarantee the unified route + tabs registries are the
single source of truth.

If someone tries to add a route by editing the legacy per-group
files directly (bypassing ``registry.ROUTES``), or adds a
Dashboard tab by editing three places instead of one, these tests
fail loudly.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dashboard" / "assets"


# ---- Route registry ------------------------------------------------------

# Historical duplicates that pre-date the unified registry. Each is
# a case where two separate subsystems both claim the same
# (method, path); aiohttp keeps the last-registered handler. Fixing
# these means either deleting the legacy handler (behaviour change)
# or moving one to a different path (breaking-change for clients).
# Left in the allowlist for now with a note; new duplicates fail
# the test.
_DUPLICATE_ROUTES_ALLOWLIST: set[tuple[str, str]] = {
    # v3.86.0 multi-agent handlers (POST/GET /v1/agents, GET/DELETE
    # /v1/agents/{id}) shadow the legacy v3.10 subagents list handler
    # ("handle_v1_agents") that was registered by domain.py. Both live
    # side by side; the multi-agent handler wins because it registers
    # second. Removing the legacy one is a follow-up.
    ("GET", "/v1/agents"),
}


def test_route_registry_no_duplicates():
    """Two Route entries with the same (method, path) are almost
    always a bug (aiohttp silently keeps whichever wins insertion
    order). Enforce uniqueness, minus a small allowlist of known
    historical overlaps that predate the unified registry."""
    from arena.route_registry.registry import all_routes
    entries = all_routes()
    counts = Counter((m, p) for m, p, _, _, _ in entries)
    dupes = [(m, p, n) for (m, p), n in counts.items() if n > 1
             and (m, p) not in _DUPLICATE_ROUTES_ALLOWLIST]
    assert not dupes, (
        "Duplicate (method, path) pairs in route registry:\n"
        + "\n".join(f"  {m} {p} × {n}" for m, p, n in dupes)
        + "\n\nIf this is intentional, add to _DUPLICATE_ROUTES_ALLOWLIST "
        + "with a comment explaining why. Otherwise, remove one of "
        + "the duplicates from ROUTES."
    )


def test_route_registry_covers_all_legacy_registrations():
    """Every route currently declared in the legacy per-group files
    MUST also appear in ``all_routes()``. If someone edits a legacy
    file directly and forgets to update the registry, we catch it."""
    from arena.route_registry.registry import all_routes
    legacy = _collect_legacy_routes()
    unified = {(m, p) for m, p, _, _, _ in all_routes()}
    missing = {(m, p) for (m, p, _) in legacy} - unified
    assert not missing, (
        "These routes are in the legacy per-group files but not in "
        "arena.route_registry.registry.all_routes():\n"
        + "\n".join(f"  {m} {p}" for m, p in sorted(missing))
    )


def test_route_registry_group_names_are_known():
    from arena.route_registry.registry import all_routes
    known = {"core", "compat", "desktop", "domain", "cdp"}
    bad = {g for _, _, _, g, _ in all_routes() if g not in known}
    assert not bad, f"unknown route groups: {bad}. Add to known set or fix ROUTES."


def test_route_registry_methods_are_valid():
    """Only real HTTP methods, uppercase."""
    from arena.route_registry.registry import all_routes
    valid = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    bad = {(m, p) for m, p, _, _, _ in all_routes() if m not in valid}
    assert not bad, f"invalid HTTP methods in registry: {bad}"


def test_route_paths_start_with_slash():
    from arena.route_registry.registry import all_routes
    bad = [(m, p) for m, p, _, _, _ in all_routes() if not p.startswith("/")]
    assert not bad, f"paths must start with '/': {bad}"


# ---- Dashboard tabs registry ---------------------------------------------

def test_tabs_registry_is_single_source_of_truth():
    """body-00-shell.html must NOT hardcode <a data-tab> links --
    they're built at boot from window.ARENA_TABS in
    00-tabs-registry.js."""
    shell = (ASSETS / "body-00-shell.html").read_text(encoding="utf-8")
    # Count `data-tab=` occurrences in the shell. Anything > 0 is a
    # hardcoded link the JS would need to duplicate.
    count = shell.count("data-tab=")
    assert count == 0, (
        f"body-00-shell.html hardcodes {count} <a data-tab=\"...\"> "
        "entries. Remove them; window.ARENA_TABS is the single source "
        "of truth, and 01-tab-switching.js builds the nav from it."
    )
    # And the placeholder div exists.
    assert 'id="arenaSidebarNav"' in shell, (
        "body-00-shell.html needs an empty <nav id=\"arenaSidebarNav\"> "
        "for the JS to populate."
    )


def test_tabs_registry_file_exists_and_declares_all_tabs():
    src = (ASSETS / "00-tabs-registry.js").read_text(encoding="utf-8")
    assert "window.ARENA_TABS" in src, "00-tabs-registry.js missing window.ARENA_TABS"
    # Each expected tab appears as `name: "X"`.
    for name in ("overview", "workspace", "terminal", "memory", "recall",
                 "missions", "browser", "reports", "tasks", "skills",
                 "hooks", "agents", "control", "mobile", "doctor",
                 "audit", "settings"):
        assert re.search(rf'name:\s*"{name}"', src), (
            f"00-tabs-registry.js is missing tab '{name}'"
        )


def test_tab_switching_uses_registry():
    """01-tab-switching.js must dispatch via the registry, not via
    hardcoded ``if (tabName === "X") loadX()`` chains."""
    src = (ASSETS / "01-tab-switching.js").read_text(encoding="utf-8")
    assert "window.ARENA_TABS" in src or "arenaTabByName" in src, (
        "01-tab-switching.js must read from window.ARENA_TABS / "
        "arenaTabByName() instead of hardcoding tab names."
    )
    # And no per-tab if/switch chain (heuristic: less than 3 direct
    # `tabName === "..."` checks left).
    hardcoded = re.findall(r'tabName\s*===\s*"[^"]+"', src)
    assert len(hardcoded) < 3, (
        f"01-tab-switching.js still has {len(hardcoded)} hardcoded "
        "`tabName === '...'` checks. Route them through the "
        "registry's onShow/onHide callbacks instead."
    )


def test_index_html_loads_tabs_registry_before_tab_switching():
    idx = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    i_reg = idx.find("00-tabs-registry.js")
    i_sw = idx.find("01-tab-switching.js")
    assert i_reg > 0, "index.html does not load 00-tabs-registry.js"
    assert i_sw > i_reg, "00-tabs-registry.js must be loaded BEFORE 01-tab-switching.js"


# ---- Helpers -------------------------------------------------------------

def _collect_legacy_routes() -> list[tuple[str, str, str]]:
    """Parse the legacy per-group register_*_routes source and return
    every (method, path, handler_name) tuple they register."""
    out: list[tuple[str, str, str]] = []
    reg_dir = ROOT / "arena" / "route_registry"
    for py in ("core.py", "compat.py", "desktop.py", "domain.py"):
        text = (reg_dir / py).read_text(encoding="utf-8")
        for m in re.finditer(
            r'app\.router\.add_(get|post|put|patch|delete|head|options)\(\s*'
            r'"([^"]+)",\s*h\[\s*"([^"]+)"\s*\]',
            text,
        ):
            out.append((m.group(1).upper(), m.group(2), m.group(3)))
    # CDP files are prefix-expanded -- parse the endpoints table.
    cdp_text = (reg_dir / "cdp.py").read_text(encoding="utf-8")
    for m in re.finditer(
        r'app\.router\.add_(get|post|put|patch|delete|head|options)'
        r'\(\s*f"\{prefix\}([^"]+)",\s*h\[\s*"([^"]+)"\s*\]',
        cdp_text,
    ):
        for prefix in ("/v1/browser/cdp", "/v1/cdp"):
            out.append((m.group(1).upper(), prefix + m.group(2), m.group(3)))
    return out
