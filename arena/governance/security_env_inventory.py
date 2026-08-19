"""Machine guard for the security environment-variable inventory."""
from __future__ import annotations

import ast
import re
from pathlib import Path

_START = "<!-- security-env-inventory:start -->"
_END = "<!-- security-env-inventory:end -->"
_ENV_NAME = re.compile(r"ARENA_[A-Z0-9_]+\Z")
_ROW = re.compile(
    r"^\s*\|\s*`(?P<name>ARENA_[A-Z0-9_]+)`\s*\|\s*"
    r"(?P<classification>security|operational|internal)\s*\|\s*"
    r"(?P<reference>exact|prefix)\s*\|\s*[^|]+?\s*\|\s*$"
)
_ROW_START = re.compile(r"^\s*\|\s*`ARENA_")
_SCAN_DIRECTORIES = ("arena", "bin", "scripts", "skills")


class SecurityEnvInventoryError(ValueError):
    """The source references and documented inventory do not agree."""


def source_references(repo_root: Path) -> dict[str, tuple[str, ...]]:
    """Return exact ARENA_* references from shipped/support Python roots."""
    scan_roots = tuple(repo_root / name for name in _SCAN_DIRECTORIES)
    paths = set(repo_root.glob("*.py"))
    for scan_root in scan_roots:
        if scan_root.is_symlink():
            raise SecurityEnvInventoryError(f"symlinked Python source: {scan_root}")
        if not scan_root.exists():
            continue
        for candidate in scan_root.rglob("*"):
            if candidate.is_symlink():
                raise SecurityEnvInventoryError(f"symlinked Python source: {candidate}")
            if candidate.is_file() and candidate.suffix == ".py":
                paths.add(candidate)

    found: dict[str, set[str]] = {}
    for path in sorted(paths):
        if path.is_symlink():
            raise SecurityEnvInventoryError(f"symlinked Python source: {path}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(repo_root).as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _ENV_NAME.fullmatch(node.value)
            ):
                found.setdefault(node.value, set()).add(relative)
    return {name: tuple(sorted(source_paths)) for name, source_paths in sorted(found.items())}


def documented_inventory(security_text: str) -> dict[str, str]:
    """Parse the bounded machine-readable table in SECURITY.md."""
    if security_text.count(_START) != 1 or security_text.count(_END) != 1:
        raise SecurityEnvInventoryError("SECURITY.md inventory markers must occur exactly once")
    bounded = re.search(
        re.escape(_START) + r"(?P<section>.*?)" + re.escape(_END),
        security_text,
        flags=re.DOTALL,
    )
    if bounded is None:
        raise SecurityEnvInventoryError("SECURITY.md inventory markers are reversed")
    section = bounded.group("section")
    inventory: dict[str, str] = {}
    for line in section.splitlines():
        match = _ROW.fullmatch(line)
        if _ROW_START.match(line) and not match:
            raise SecurityEnvInventoryError(f"malformed SECURITY.md inventory row: {line}")
        if not match:
            continue
        name = match.group("name")
        reference = match.group("reference")
        if name.endswith("_") != (reference == "prefix"):
            raise SecurityEnvInventoryError(
                f"SECURITY.md exact/prefix classification mismatch: {name}"
            )
        if name in inventory:
            raise SecurityEnvInventoryError(f"duplicate SECURITY.md inventory row: {name}")
        inventory[name] = match.group("classification")
    if not inventory:
        raise SecurityEnvInventoryError("SECURITY.md environment inventory is empty")
    return inventory


def verify_inventory(repo_root: Path, security_file: Path) -> None:
    """Fail unless every source reference has exactly one classification."""
    source = source_references(repo_root)
    documented = set(documented_inventory(security_file.read_text(encoding="utf-8")))
    missing = sorted(set(source) - documented)
    extra = sorted(documented - set(source))
    if missing or extra:
        details = []
        if missing:
            located = (
                f"{name} ({', '.join(source[name])})"
                for name in missing
            )
            details.append("undocumented source references: " + ", ".join(located))
        if extra:
            details.append("stale documented references: " + ", ".join(extra))
        raise SecurityEnvInventoryError("; ".join(details))
