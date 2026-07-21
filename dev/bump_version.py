#!/usr/bin/env python3
"""Release version bump helper.

Bumps the bridge version across the three files that MUST stay in sync
per the AGENTS.md release rule:

  1. ``arena/constants.py``          — ``VERSION = "…"``
  2. ``pyproject.toml``              — ``version = "…"``
  3. ``tests/_version_matrix.py``    — append to ``BRIDGE_VERSIONS`` tuple

Usage
-----
    # Bump the bridge (arena/constants.py + pyproject.toml + BRIDGE_VERSIONS)
    python dev/bump_version.py 4.60.7
    python dev/bump_version.py --dry-run 4.60.7

    # Bump the browser extension manifest + content.js + insert_strategies.js
    # + append to tests/_version_matrix.EXT_VERSIONS (rare, only when the
    # extension actually changed)
    python dev/bump_version.py --extension 0.14.43

The script is intentionally conservative: it fails if the new version
is already present, if the target file cannot be parsed, or if any of
the rewrites produces an invalid Python / JSON file.

The script does NOT:
  * touch CHANGELOG.md / CHANGELOG.ru.md (release notes are hand-written)
  * git-commit, tag, or push
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PY = REPO_ROOT / "arena" / "constants.py"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"
VERSION_MATRIX_PY = REPO_ROOT / "tests" / "_version_matrix.py"

# Extension files (only touched by --extension)
CHAT_EXT_DIR = REPO_ROOT / "chat_extension"
EXT_MANIFEST_JSON = CHAT_EXT_DIR / "manifest.json"
EXT_CONTENT_JS = CHAT_EXT_DIR / "content.js"
EXT_INSERT_JS = CHAT_EXT_DIR / "insert_strategies.js"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _die(msg: str) -> None:
    sys.stderr.write(f"bump_version: {msg}\n")
    sys.exit(1)


def _bump_constants(new: str, *, dry_run: bool) -> str:
    src = CONSTANTS_PY.read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"\s*$', src, re.MULTILINE)
    if not m:
        _die(f"{CONSTANTS_PY} has no matching VERSION assignment")
    old = m.group(1)
    if old == new:
        _die(f"{CONSTANTS_PY}: VERSION already at {new}")
    updated = src[: m.start()] + f'VERSION = "{new}"' + src[m.end():]
    if not dry_run:
        CONSTANTS_PY.write_text(updated, encoding="utf-8")
    return f"{CONSTANTS_PY.relative_to(REPO_ROOT)}: {old} -> {new}"


def _bump_pyproject(new: str, *, dry_run: bool) -> str:
    src = PYPROJECT_TOML.read_text(encoding="utf-8")
    # Match only the top-level [project] version = "..." — not build-system deps
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', src)
    if not m:
        _die(f"{PYPROJECT_TOML} has no matching version line")
    old = m.group(1)
    if old == new:
        _die(f"{PYPROJECT_TOML}: version already at {new}")
    updated = src[: m.start()] + f'version = "{new}"' + src[m.end():]
    if not dry_run:
        PYPROJECT_TOML.write_text(updated, encoding="utf-8")
    return f"{PYPROJECT_TOML.relative_to(REPO_ROOT)}: {old} -> {new}"


def _bump_version_matrix(new: str, *, dry_run: bool) -> str:
    src = VERSION_MATRIX_PY.read_text(encoding="utf-8")
    # Locate the BRIDGE_VERSIONS = ( ... ) block via AST for robustness.
    # Deliberately do NOT string-search the whole file: docstrings can
    # legitimately mention example versions like ``VERSION = "4.60.7"``.
    tree = ast.parse(src)
    node = None
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "BRIDGE_VERSIONS"
        ):
            node = stmt.value
            break
        if (
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "BRIDGE_VERSIONS" for t in stmt.targets)
        ):
            node = stmt.value
            break
    if node is None:
        _die(f"{VERSION_MATRIX_PY}: cannot find BRIDGE_VERSIONS assignment")
    if not isinstance(node, ast.Tuple):
        _die(f"{VERSION_MATRIX_PY}: BRIDGE_VERSIONS is not a literal tuple")
    if not node.elts:
        _die(f"{VERSION_MATRIX_PY}: BRIDGE_VERSIONS tuple is empty")
    existing = [
        el.value for el in node.elts
        if isinstance(el, ast.Constant) and isinstance(el.value, str)
    ]
    if new in existing:
        _die(f"{VERSION_MATRIX_PY}: {new!r} already present in BRIDGE_VERSIONS")
    last = node.elts[-1]
    if not isinstance(last, ast.Constant) or not isinstance(last.value, str):
        _die(f"{VERSION_MATRIX_PY}: last BRIDGE_VERSIONS entry is not a string literal")
    # Compute character offsets (Python 3.8+ end_col_offset available).
    lines = src.splitlines(keepends=True)
    # Convert (lineno, col_offset) -> absolute index
    def _idx(lineno: int, col: int) -> int:
        return sum(len(ln) for ln in lines[: lineno - 1]) + col

    last_end = _idx(last.end_lineno, last.end_col_offset)
    # Insert `,\n    "<new>"` after the last string literal — preserve the
    # existing trailing comma style by mirroring what's already there.
    tail = src[last_end:]
    # Detect indentation of the last element by looking at the last line
    last_line_start = src.rfind("\n", 0, _idx(last.lineno, last.col_offset)) + 1
    indent = src[last_line_start : _idx(last.lineno, last.col_offset)]
    if "," in tail[:2]:
        # already comma-terminated — insert after the comma
        insert_at = last_end + tail.index(",") + 1
        addition = f'\n{indent}"{new}",'
    else:
        insert_at = last_end
        addition = f',\n{indent}"{new}"'
    updated = src[:insert_at] + addition + src[insert_at:]
    # Sanity: parse updated file
    try:
        ast.parse(updated)
    except SyntaxError as exc:
        _die(f"{VERSION_MATRIX_PY}: rewrite produced invalid Python ({exc})")
    if not dry_run:
        VERSION_MATRIX_PY.write_text(updated, encoding="utf-8")
    return f"{VERSION_MATRIX_PY.relative_to(REPO_ROOT)}: appended {new!r} to BRIDGE_VERSIONS"


def _bump_ext_matrix(new: str, *, dry_run: bool) -> str:
    """Append ``new`` to ``EXT_VERSIONS`` in ``_version_matrix.py``."""
    src = VERSION_MATRIX_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = None
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "EXT_VERSIONS"
        ):
            node = stmt.value
            break
        if (
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "EXT_VERSIONS" for t in stmt.targets)
        ):
            node = stmt.value
            break
    if node is None:
        _die(f"{VERSION_MATRIX_PY}: cannot find EXT_VERSIONS assignment")
    if not isinstance(node, ast.Tuple) or not node.elts:
        _die(f"{VERSION_MATRIX_PY}: EXT_VERSIONS is not a non-empty literal tuple")
    existing = [
        el.value for el in node.elts
        if isinstance(el, ast.Constant) and isinstance(el.value, str)
    ]
    if new in existing:
        _die(f"{VERSION_MATRIX_PY}: {new!r} already present in EXT_VERSIONS")
    last = node.elts[-1]
    if not isinstance(last, ast.Constant) or not isinstance(last.value, str):
        _die(f"{VERSION_MATRIX_PY}: last EXT_VERSIONS entry is not a string literal")
    lines = src.splitlines(keepends=True)
    def _idx(lineno: int, col: int) -> int:
        return sum(len(ln) for ln in lines[: lineno - 1]) + col
    last_end = _idx(last.end_lineno, last.end_col_offset)
    last_line_start = src.rfind("\n", 0, _idx(last.lineno, last.col_offset)) + 1
    indent = src[last_line_start : _idx(last.lineno, last.col_offset)]
    tail = src[last_end:]
    if "," in tail[:2]:
        insert_at = last_end + tail.index(",") + 1
        addition = f'\n{indent}"{new}",'
    else:
        insert_at = last_end
        addition = f',\n{indent}"{new}"'
    updated = src[:insert_at] + addition + src[insert_at:]
    try:
        ast.parse(updated)
    except SyntaxError as exc:
        _die(f"{VERSION_MATRIX_PY}: rewrite produced invalid Python ({exc})")
    if not dry_run:
        VERSION_MATRIX_PY.write_text(updated, encoding="utf-8")
    return f"{VERSION_MATRIX_PY.relative_to(REPO_ROOT)}: appended {new!r} to EXT_VERSIONS"


def _bump_ext_manifest(new: str, *, dry_run: bool) -> str:
    src = EXT_MANIFEST_JSON.read_text(encoding="utf-8")
    data = json.loads(src)
    old = data.get("version")
    if old == new:
        _die(f"{EXT_MANIFEST_JSON}: version already at {new}")
    data["version"] = new
    updated = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    # Round-trip validate
    json.loads(updated)
    if not dry_run:
        EXT_MANIFEST_JSON.write_text(updated, encoding="utf-8")
    return f"{EXT_MANIFEST_JSON.relative_to(REPO_ROOT)}: {old} -> {new}"


def _bump_ext_content_js(new: str, *, dry_run: bool) -> str:
    src = EXT_CONTENT_JS.read_text(encoding="utf-8")
    m = re.search(r"^const ARENA_CONTENT_SCRIPT_VERSION = '([^']+)';\s*$", src, re.MULTILINE)
    if not m:
        _die(f"{EXT_CONTENT_JS}: cannot find ARENA_CONTENT_SCRIPT_VERSION assignment")
    old = m.group(1)
    if old == new:
        _die(f"{EXT_CONTENT_JS}: already at {new}")
    updated = src[: m.start()] + f"const ARENA_CONTENT_SCRIPT_VERSION = '{new}';" + src[m.end():]
    if not dry_run:
        EXT_CONTENT_JS.write_text(updated, encoding="utf-8")
    return f"{EXT_CONTENT_JS.relative_to(REPO_ROOT)}: {old} -> {new}"


def _bump_ext_insert_js(new: str, *, dry_run: bool) -> str:
    src = EXT_INSERT_JS.read_text(encoding="utf-8")
    # There may be multiple ``return '0.14.X';`` — take the one under the
    # ``arenaExtensionVersion`` or similar helper. Simplest safe replace:
    # rewrite every ``return '0.14.\d+';`` occurrence.
    pat = re.compile(r"return '0\.\d+\.\d+';")
    matches = pat.findall(src)
    if not matches:
        _die(f"{EXT_INSERT_JS}: cannot find any return '0.X.Y'; literal")
    olds = {m for m in matches}
    updated = pat.sub(f"return '{new}';", src)
    if updated == src:
        _die(f"{EXT_INSERT_JS}: no-op rewrite")
    if not dry_run:
        EXT_INSERT_JS.write_text(updated, encoding="utf-8")
    old_desc = ",".join(sorted(olds))
    return f"{EXT_INSERT_JS.relative_to(REPO_ROOT)}: {old_desc} -> return '{new}'; ({len(matches)} occurrences)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("version", help='new version, e.g. "4.60.7" (bridge) or "0.14.43" (--extension)')
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change; do not write files",
    )
    ap.add_argument(
        "--extension",
        action="store_true",
        help="bump the browser extension (manifest + content.js + insert_strategies.js + EXT_VERSIONS) instead of the bridge",
    )
    args = ap.parse_args(argv)
    if not VERSION_RE.match(args.version):
        _die(f"invalid version {args.version!r} — expected X.Y.Z")

    if args.extension:
        results = [
            _bump_ext_manifest(args.version, dry_run=args.dry_run),
            _bump_ext_content_js(args.version, dry_run=args.dry_run),
            _bump_ext_insert_js(args.version, dry_run=args.dry_run),
            _bump_ext_matrix(args.version, dry_run=args.dry_run),
        ]
        summary = f"Extension bumped to {args.version}."
    else:
        results = [
            _bump_constants(args.version, dry_run=args.dry_run),
            _bump_pyproject(args.version, dry_run=args.dry_run),
            _bump_version_matrix(args.version, dry_run=args.dry_run),
        ]
        summary = f"Bridge bumped to {args.version}."

    prefix = "[dry-run] " if args.dry_run else ""
    for line in results:
        print(f"{prefix}{line}")
    if args.dry_run:
        print("[dry-run] no files written")
    else:
        print(f"{summary} Next: update CHANGELOG.md / CHANGELOG.ru.md, then run pytest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
