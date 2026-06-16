"""Repository-wide modularity guards for v3.1+.

These tests intentionally look beyond ``unified_bridge.py``.  The v3.0 release
made the bridge runtime modular; v3.1 keeps secondary CLI/script/dashboard files
from growing back into hidden monoliths.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_PRODUCT_FILE_LINES = 200
ENTRYPOINT_LIMITS = {
    "unified_bridge.py": 150,
    "bin/agentctl": 80,
    "scripts/inventory.py": 80,
    "scripts/skill_runner.py": 80,
    "scripts/mcp_stream_server.py": 80,
    "scripts/mcp_ws_server.py": 80,
    "scripts/memory.py": 80,
    "scripts/desktop_manager.py": 80,
    "scripts/hwinfo.py": 80,
    "scripts/agent_helpers.py": 80,
    "scripts/project_git.py": 80,
    "scripts/mission_manager.py": 80,
    "bin/memory_recall.py": 80,
    "bin/mcp_marketplace.py": 80,
}
EXCLUDE_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "tests",
    "tools",
    "dev",
    "docs",
}
SUFFIXES = {".py", ".js", ".html", ".css", ".sh", ".bat", ".ps1"}
EXTRA_FILES = {Path("bin/agentctl")}
# Platform installers are intentionally procedural deployment scripts; runtime and
# agent-facing code must stay modular, but installer refactors are validated by
# fresh-install smoke tests instead of line-count gates.
DEPLOYMENT_ALLOWLIST = {
    Path("install.sh"),
    Path("install.bat"),
    Path("uninstall.sh"),
    Path("uninstall.bat"),
    Path("scripts/install_windows_service.ps1"),
}


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))


def _product_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        if rel in DEPLOYMENT_ALLOWLIST:
            continue
        if path.suffix in SUFFIXES or rel in EXTRA_FILES:
            files.append(path)
    return files


def test_product_files_stay_under_modularity_line_limit():
    offenders = []
    for path in _product_files():
        rel = path.relative_to(ROOT)
        lines = _line_count(path)
        if lines > MAX_PRODUCT_FILE_LINES:
            offenders.append((str(rel), lines))
    assert offenders == []


def test_compatibility_entrypoints_are_thin_wrappers():
    offenders = []
    for rel_s, limit in ENTRYPOINT_LIMITS.items():
        path = ROOT / rel_s
        assert path.exists(), rel_s
        lines = _line_count(path)
        if lines > limit:
            offenders.append((rel_s, lines, limit))
    assert offenders == []


def test_transitional_wiring_does_not_mutate_module_globals():
    offenders = []
    for path in (ROOT / "arena" / "wiring").glob("legacy_*.py"):
        text = path.read_text(encoding="utf-8")
        if "globals().update(" in text or "ruff: noqa: F821" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
