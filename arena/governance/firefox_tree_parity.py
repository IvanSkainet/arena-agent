"""Pure generated-tree parity for Chromium and Firefox extension sources."""
from __future__ import annotations

import json
from pathlib import Path


def tree_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix != ".zip"
        and "__pycache__" not in path.parts
    }


def normalized_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return raw


def verify_generated_tree(
    source: Path,
    target: Path,
    firefox_manifest: dict,
) -> list[str]:
    """Return checked-in Firefox drift from the generated source of truth."""
    source_names = tree_files(source)
    target_names = tree_files(target) if target.exists() else set()
    problems = [
        f"missing generated file: {name}"
        for name in sorted(source_names - target_names)
    ]
    problems.extend(
        f"unexpected generated file: {name}"
        for name in sorted(target_names - source_names)
    )
    for name in sorted((source_names & target_names) - {"manifest.json"}):
        if normalized_bytes(source / name) != normalized_bytes(target / name):
            problems.append(f"generated file drifted: {name}")
    if "manifest.json" in target_names:
        expected = (
            json.dumps(firefox_manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if normalized_bytes(target / "manifest.json") != expected:
            problems.append("generated Firefox manifest drifted")
    return problems
