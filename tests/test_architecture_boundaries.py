"""Architecture regression tests for the modular v3 bridge layout."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARENA = ROOT / "arena"
LINE_ALLOWLIST = {
    Path("arena/gui/templates.py"),
    Path("arena/mobile/handlers.py"),
    # v4.34.0: registry.py is a single-source-of-truth data
    # manifest (46 inventory Section entries + one small helper
    # formatter per section). Growing it past 600 lines happens
    # naturally as inventory coverage expands; the file has no
    # runtime logic beyond the format_lines helpers, so the
    # "modular runtime" threshold doesn't apply. A future split
    # could move format_lines to a sibling module if needed.
    Path("arena/inventory/registry.py"),
    # v4.38.1: admin/handlers.py is by nature a dispatcher --
    # it grows with the number of endpoints (currently ~30 admin
    # verbs across tunnels / tokens / breakers / autostart /
    # proposals / update / zerotier / ...). The heavy per-verb
    # logic already lives in sibling modules:
    #   * handlers_proposal.py (v4.19.0, proposal endpoints)
    #   * handlers_update.py   (v3.85.0, auto-update endpoints)
    #   * handlers_autostart.py (v4.38.0, autostart endpoints)
    #   * zerotier_central_handlers.py (v3.96.0)
    # What remains here is 30-ish thin dispatch closures that
    # bind the request object to the sync-worker equivalent.
    # Splitting further would fragment the "one file per admin
    # concern" mental model without reducing runtime complexity.
    # Reviewer note: if a NEW multi-line concern appears here,
    # it should follow the sibling-module pattern rather than
    # inflating this allowlist.
    Path("arena/admin/handlers.py"),
}
MAX_RUNTIME_LINES = 600
MAX_UNIFIED_BRIDGE_LINES = 150


def _py_files() -> list[Path]:
    return [p for p in ARENA.rglob("*.py") if "__pycache__" not in p.parts]


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8"))


def test_unified_bridge_is_thin_entrypoint():
    assert _line_count(ROOT / "unified_bridge.py") <= MAX_UNIFIED_BRIDGE_LINES


def test_arena_modules_do_not_import_unified_bridge():
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name == "unified_bridge" for alias in node.names):
                offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.ImportFrom) and node.module == "unified_bridge":
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_runtime_modules_stay_below_mini_monolith_threshold():
    offenders = []
    for path in _py_files():
        rel = path.relative_to(ROOT)
        if rel in LINE_ALLOWLIST:
            continue
        lines = _line_count(path)
        if lines > MAX_RUNTIME_LINES:
            offenders.append((str(rel), lines))
    assert offenders == []


def test_core_modular_directories_exist():
    expected = [
        "contexts",
        "route_registry",
        "wiring",
        "runtime_deps",
        "browser",
        "desktop",
        "service",
        "system",
        "memory",
        "observability",
        "mcp",
    ]
    missing = [name for name in expected if not (ARENA / name).is_dir()]
    assert missing == []
