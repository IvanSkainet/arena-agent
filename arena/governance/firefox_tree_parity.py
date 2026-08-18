"""Pure generated-tree parity for Chromium and Firefox extension sources."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

_TEXT_SUFFIXES = frozenset({".css", ".html", ".js", ".json", ".md"})


def excluded_path(relative: Path) -> bool:
    return any(
        part == "__pycache__" or part.lower().endswith(".zip")
        for part in relative.parts
    )


def ignored_names(_directory: str, names: Iterable[str]) -> set[str]:
    """copytree ignore callback matching the parity exclusion policy."""
    return {
        name
        for name in names
        if name == "__pycache__" or name.lower().endswith(".zip")
    }


def symlink_entries(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_symlink() and not excluded_path(path.relative_to(root))
    }


def tree_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not excluded_path(path.relative_to(root))
    }


def comparable_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return raw
    return raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")


def verify_generated_tree(
    source: Path,
    target: Path,
    firefox_manifest: dict,
) -> list[str]:
    """Return checked-in Firefox drift from the generated source of truth."""
    source_links = symlink_entries(source)
    target_links = symlink_entries(target) if target.exists() else set()
    problems = [
        f"symlink not allowed in Chromium source: {name}"
        for name in sorted(source_links)
    ]
    problems.extend(
        f"symlink not allowed in generated Firefox tree: {name}"
        for name in sorted(target_links)
    )
    source_names = tree_files(source)
    target_names = tree_files(target) if target.exists() else set()
    problems.extend(
        f"missing generated file: {name}"
        for name in sorted(source_names - target_names)
    )
    problems.extend(
        f"unexpected generated file: {name}"
        for name in sorted(target_names - source_names)
    )
    for name in sorted((source_names & target_names) - {"manifest.json"}):
        if comparable_bytes(source / name) != comparable_bytes(target / name):
            problems.append(f"generated file drifted: {name}")
    if "manifest.json" in target_names:
        expected = (
            json.dumps(firefox_manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if comparable_bytes(target / "manifest.json") != expected:
            problems.append("generated Firefox manifest drifted")
    return problems
