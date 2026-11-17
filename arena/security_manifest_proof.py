"""Conservative, non-executing proof of patched Python manifests (#477).

TOML proof requires Python 3.11+ (the workflow uses 3.12). On Python 3.10,
requirements proof remains supported but TOML deliberately stays blocking.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

MAX_MANIFEST_BYTES = 512 * 1024
_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_., -]+\])?\s*(.*)$")
_BOUND = re.compile(
    r"(==|~=|>=|<=|!=|>|<)\s*(\d+(?:\.\d+)*"
    r"(?:(?:a|b|rc|\.post|\.dev)\d+)*(?:\+[A-Za-z0-9.]+)?(?:\.\*)?)"
)


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def numeric_version(version: str) -> tuple[int, ...] | None:
    if len(version) > 256 or not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return None
    return tuple(map(int, version.split(".")))


def numeric_at_least(candidate: str, minimum: str) -> bool:
    left, right = numeric_version(candidate), numeric_version(minimum)
    if left is None or right is None:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))


def _flatten_arrays(arrays: list[Any]) -> list[str] | None:
    if any(not isinstance(array, list) for array in arrays):
        return None
    items = [item for array in arrays for item in array]
    return items if all(isinstance(item, str) for item in items) else None


def _other_project_arrays(doc: dict[str, Any]) -> list[Any] | None:
    # Unknown dependency managers can define extra requirements/overrides.
    # Only non-resolver tool tables used by this repository are supported.
    tools = doc.get("tool", {})
    known_tools = {"setuptools", "ruff", "pytest", "coverage", "mypy", "vulture", "importlinter"}
    if not isinstance(tools, dict) or set(tools) - known_tools:
        return None
    build, groups = doc.get("build-system", {}), doc.get("dependency-groups", {})
    if not isinstance(build, dict) or not isinstance(groups, dict):
        return None
    return [build.get("requires", []), *groups.values()]


def _project_arrays(project: Any) -> list[Any] | None:
    if not isinstance(project, dict) or project.get("dynamic"):
        return None
    groups = project.get("optional-dependencies", {})
    if not isinstance(groups, dict):
        return None
    return [project.get("dependencies", []), *groups.values()]


def _toml_document(text: str) -> dict[str, Any] | None:
    # Workflows use Python 3.12; older interpreters retain unsupported alerts.
    try:
        import tomllib
        return tomllib.loads(text)
    except (ImportError, ValueError):
        return None


def _project_dependencies(text: str) -> list[str] | None:
    doc = _toml_document(text)
    if doc is None:
        return None
    arrays, other = _project_arrays(doc.get("project", {})), _other_project_arrays(doc)
    if arrays is None or other is None:
        return None
    return _flatten_arrays([*arrays, *other])


def _requirement_lines(path: str, text: str) -> list[str] | None:
    if path.endswith("pyproject.toml"):
        return _project_dependencies(text)
    if text.rstrip().endswith("\\"):
        return None
    joined = re.sub(r"\\\r?\n", " ", text)
    lines = [line.split("#", 1)[0].strip() for line in joined.splitlines()]
    return [line for line in lines if line]


def _declaration(line: str) -> tuple[str, list[tuple[str, str]]] | None:
    # Check EVERY marker variant, not just the runner's environment. An older
    # supported Python/platform must not retain a vulnerable declaration.
    requirement = line.split(";", 1)[0]
    requirement = re.sub(r"\s+--hash=sha256:[a-fA-F0-9]{64}", "", requirement).strip()
    match = _NAME.fullmatch(requirement)
    if match is None:
        return None
    name, specifier = match.groups()
    bounds = []
    if not specifier:
        return normalise(name), bounds
    for part in specifier.split(","):
        bound = _BOUND.fullmatch(part.strip())
        if bound is None:
            return None
        bounds.append((bound[1], bound[2]))
    return normalise(name), bounds


def _parse_declarations(lines: list[str]) -> list[tuple[str, list[tuple[str, str]]]] | None:
    parsed = []
    for line in lines:
        declaration = _declaration(line)
        if declaration is None:
            return None  # Includes, URLs, unsupported syntax: no proof.
        parsed.append(declaration)
    return parsed


def _patched_bounds(bounds: list[tuple[str, str]], minimum: str) -> bool:
    return any(op in ("==", ">=", "~=") and numeric_at_least(version, minimum)
               for op, version in bounds)


def _package_is_patched(
    declarations: list[tuple[str, list[tuple[str, str]]]], package: str, minimum: str,
) -> bool:
    matching = [bounds for name, bounds in declarations if name == normalise(package)]
    # Absence does not prove removal of a transitive dependency.
    return bool(matching) and all(_patched_bounds(bounds, minimum) for bounds in matching)


def manifest_fixes(path: str, text: str, package: str, minimum: str) -> bool:
    """Every declaration of this package must exclude numeric vulnerable versions."""
    lines = _requirement_lines(path, text)
    declarations = _parse_declarations(lines) if lines is not None else None
    if declarations is None:
        return False
    return _package_is_patched(declarations, package, minimum)


def _complete_tree_entries(tree: dict[str, Any]) -> list[dict[str, Any]] | None:
    entries = tree.get("tree")
    if tree.get("truncated") is not False or not isinstance(entries, list):
        return None
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return None
    return entries


def _unsafe_ancestor(item: dict[str, Any], path: str) -> bool:
    return path.startswith(item["path"] + "/") and item.get("mode") in ("120000", "160000")


def _entry_blob(item: dict[str, Any]) -> tuple[str, str]:
    if item.get("type") != "blob" or item.get("mode") not in ("100644", "100755"):
        return "unknown", ""
    sha = item.get("sha", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        return "unknown", ""
    return "file", sha


def tree_manifest(tree: dict[str, Any], path: str) -> tuple[str, str]:
    """Return file/blob, absent, or unknown; never follow symlinks/submodules."""
    entries = _complete_tree_entries(tree)
    if entries is None:
        return "unknown", ""
    if any(_unsafe_ancestor(item, path) for item in entries):
        return "unknown", ""
    entry = next((item for item in entries if item["path"] == path), None)
    return _entry_blob(entry) if entry is not None else ("absent", "")


def _blob_metadata_valid(blob: dict[str, Any], sha: str) -> bool:
    return (blob.get("sha") == sha and blob.get("encoding") == "base64")


def _blob_payload(blob: dict[str, Any]) -> tuple[str, int] | None:
    content, size = blob.get("content"), blob.get("size")
    if not isinstance(content, str) or not isinstance(size, int):
        return None
    if not 0 <= size <= MAX_MANIFEST_BYTES or len(content) > MAX_MANIFEST_BYTES * 2:
        return None
    return content, size


def decode_manifest(blob: dict[str, Any], sha: str) -> str | None:
    """Reject incomplete, mismatched or oversized API blobs."""
    if not _blob_metadata_valid(blob, sha):
        return None
    payload = _blob_payload(blob)
    if payload is None:
        return None
    content, size = payload
    try:
        raw = base64.b64decode("".join(content.splitlines()), validate=True)
        return raw.decode("utf-8") if len(raw) == size else None
    except (binascii.Error, UnicodeError, ValueError):
        return None
