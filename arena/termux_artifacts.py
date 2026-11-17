"""Per-interpreter coverage of Android/arm64 and universal PyPI artifacts."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.utils import InvalidWheelFilename, parse_wheel_filename
else:
    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.utils import InvalidWheelFilename, parse_wheel_filename
    except ImportError:
        from pip._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
        from pip._vendor.packaging.utils import InvalidWheelFilename, parse_wheel_filename


def _python_matches(requirement: str, version: str) -> bool:
    try:
        return not requirement or SpecifierSet(requirement).contains(version)
    except InvalidSpecifier:
        return False


def _interpreter_matches(interpreter: str, abi: str, version: str) -> bool:
    code = version.replace(".", "")
    if interpreter in ("py3", "py" + code, "cp" + code):
        return True
    if abi == "abi3" and interpreter.startswith("cp3"):
        return int(interpreter[3:]) <= int(version.split(".")[1])
    return False


def _platform_matches(platform: str) -> bool:
    return platform == "any" or (
        "android_" in platform and ("arm64_v8a" in platform or "aarch64" in platform))


def _wheel_matches(filename: str, version: str) -> bool:
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return any(_platform_matches(tag.platform) and _interpreter_matches(tag.interpreter, tag.abi, version)
               for tag in tags)


def _artifact_matches(entry: dict, version: str, fallback: str) -> bool:
    if entry.get("yanked", False):
        return False
    if not _python_matches(entry.get("requires_python") or fallback, version):
        return False
    if entry.get("packagetype") == "sdist":
        return True
    return entry.get("packagetype") == "bdist_wheel" and _wheel_matches(entry["filename"], version)


def usable_hashes(detail: dict, versions: tuple[str, ...]) -> list[str]:
    """Every supported interpreter needs an artifact; retain the union of hashes."""
    fallback = detail.get("info", {}).get("requires_python") or ""
    entries = detail.get("urls", [])
    hashes: set[str] = set()
    for version in versions:
        compatible = [entry for entry in entries if _artifact_matches(entry, version, fallback)]
        if not compatible:
            return []
        hashes.update(entry["digests"]["sha256"] for entry in compatible)
    return sorted(hashes)
