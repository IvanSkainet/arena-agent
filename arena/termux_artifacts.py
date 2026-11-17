"""Per-interpreter coverage of Android/arm64 and universal PyPI artifacts."""
from __future__ import annotations

import re
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


# Conservative artifact floor: retain compatibility with Android 7/API 24.
# Device validation currently uses Android 16/API 36; this is not a claim
# that all dependency source builds have been exercised on older Android.
MIN_ANDROID_API = 24


def _python_matches(requirement: str, version: str) -> bool:
    try:
        return not requirement or SpecifierSet(requirement).contains(version)
    except InvalidSpecifier:
        return False


def _interpreter_matches(interpreter: str, abi: str, version: str) -> bool:
    code = version.replace(".", "")
    if interpreter in ("py3", "py" + code):
        return abi == "none"
    if interpreter == "cp" + code:
        return abi in ("none", "abi3", "cp" + code)
    if abi != "abi3":
        return False
    return _stable_abi_interpreter(interpreter, version)


def _stable_abi_interpreter(interpreter: str, version: str) -> bool:
    # Stable ABI is defined only for CPython3; bounded ASCII digits avoid
    # malformed/unbounded integer conversion on untrusted wheel filenames.
    if not re.fullmatch(r"cp3\d{1,2}", interpreter, flags=re.ASCII):
        return False
    return int(interpreter[3:]) <= int(version.split(".")[1])


def _platform_matches(platform: str) -> bool:
    if platform == "any":
        return True
    match = re.fullmatch(r"android_(\d{1,3})_(?:arm64_v8a|aarch64)", platform, flags=re.ASCII)
    return bool(match and 1 <= int(match.group(1)) <= MIN_ANDROID_API)


def _tag_matches(tag, version: str) -> bool:
    return _platform_matches(tag.platform) and _interpreter_matches(tag.interpreter, tag.abi, version)


def _wheel_matches(filename: str, version: str) -> bool:
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return any(_tag_matches(tag, version) for tag in tags)


def _artifact_matches(entry: dict, version: str, fallback: str) -> bool:
    if entry.get("yanked", False):
        return False
    if not _python_matches(entry.get("requires_python") or fallback, version):
        return False
    if entry.get("packagetype") == "sdist":
        return True
    return entry.get("packagetype") == "bdist_wheel" and _wheel_matches(entry["filename"], version)


def _additional_wheel_versions(entry: dict) -> set[str]:
    # Retaining a published wheel digest is not a claim of tested support.
    # Coverage remains mandatory for the explicit CI matrix below, but pip on
    # a newer CPython must not select a valid wheel whose hash we discarded.
    if entry.get("packagetype") != "bdist_wheel" or entry.get("yanked", False):
        return set()
    try:
        _, _, _, tags = parse_wheel_filename(entry["filename"])
    except InvalidWheelFilename:
        return set()
    return {"3." + tag.interpreter[3:] for tag in tags
            if re.fullmatch(r"cp3\d{1,2}", tag.interpreter, flags=re.ASCII)
            and _platform_matches(tag.platform)}


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
    for entry in entries:
        if any(_artifact_matches(entry, version, fallback)
               for version in _additional_wheel_versions(entry)):
            hashes.add(entry["digests"]["sha256"])
    return sorted(hashes)
