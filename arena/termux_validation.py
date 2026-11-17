"""Validate selected metadata against the complete on-device dependency lock."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packaging.requirements import Requirement
else:
    try:
        from packaging.requirements import Requirement
    except ImportError:
        from pip._vendor.packaging.requirements import Requirement


def _name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def _environments(versions: tuple[str, ...]):
    for version in versions:
        for system, platform in (("Android", "android"), ("Linux", "linux")):
            yield {"implementation_name": "cpython", "implementation_version": version + ".0",
                   "os_name": "posix", "platform_machine": "aarch64", "platform_release": "",
                   "platform_system": system, "platform_version": "",
                   "python_full_version": version + ".0", "python_version": version,
                   "platform_python_implementation": "CPython", "sys_platform": platform, "extra": ""}


def _active(requirement: Requirement, versions: tuple[str, ...]) -> bool:
    if requirement.marker is None:
        return True
    marker = str(requirement.marker)
    if any(key in marker for key in ("platform_release", "platform_version",
                                     "python_full_version", "implementation_version")):
        raise RuntimeError(f"cannot prove device-specific dependency marker: {marker}")
    return any(requirement.marker.evaluate(env) for env in _environments(versions))


def _validate_requirement(text: str, known: dict[str, str], versions: tuple[str, ...]) -> None:
    requirement = Requirement(text)
    if not _active(requirement, versions):
        return
    if requirement.url or requirement.extras:
        raise RuntimeError(f"unsupported dependency URL/extras in selected release: {requirement}")
    version = known.get(_name(requirement.name))
    if version is None or not requirement.specifier.contains(version, prereleases=True):
        raise RuntimeError(f"selected lock does not satisfy {requirement}")


def _requirement_list(value, package: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"invalid dependency metadata for {package}")
    return value


def _requirements(detail: dict, package: str) -> list[str]:
    info = detail.get("info")
    if not isinstance(info, dict) or "requires_dist" not in info:
        raise RuntimeError(f"missing dependency metadata for {package}")
    return _requirement_list(info["requires_dist"], package)


def validate_closure(
    rows: list[tuple[str, str, list[str]]], fetch: Callable[[str], dict],
    versions: tuple[str, ...], *, installed: list[tuple[str, str, list[str]]] | None = None,
) -> None:
    """Validate real requires_dist without executing downloaded package code."""
    known = {_name(package): version for package, version, _ in [*(installed or []), *rows]}
    for package, version, _ in rows:
        detail = fetch(f"https://pypi.org/pypi/{package}/{version}/json")
        for requirement in _requirements(detail, package):
            _validate_requirement(requirement, known, versions)
