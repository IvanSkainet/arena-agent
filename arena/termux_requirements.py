#!/usr/bin/env python3
"""Regenerate the hash-pinned requirements file for the Termux install."""
#
# Scorecard alerts #317/#318/#319 flagged `scripts/install_termux.sh` for
# running bare `pip install aiohttp` / `pip install psutil`. Unpinned is
# bad anywhere; it is worse here, because the package lands on the
# operator's *phone* and the bridge that imports it runs with shell
# access on a device that roams between untrusted networks.
#
# The fix is `pip install --require-hashes -r scripts/requirements-termux.txt`,
# which needs every artifact -- including transitive dependencies --
# listed with its digest. Maintaining that by hand rots immediately, so
# this script rebuilds it from PyPI.
#
# Two deliberate choices:
#
# * **Hashes for several artifacts per package.** Termux on arm64 usually
#   builds `aiohttp` from the sdist because no manylinux wheel matches its
#   Bionic libc, but pip will happily take a wheel when the ABI *does*
#   match. A hash set that omits the artifact pip actually chooses makes
#   the install fail rather than silently skip the check -- so both the
#   sdist and Android/arm64 / pure-Python wheels are recorded.
#
# * **Refuses to write a file it could not verify.** If any package or
#   version cannot be resolved, nothing is written. A half-generated
#   requirements file that happens to satisfy pip is exactly the kind of
#   quiet failure this whole exercise is against.
#
# Usage:
#     python -m pip install packaging  # generator prerequisite, not a runtime dependency
#     python scripts/refresh_termux_requirements.py            # rewrite
#     python scripts/refresh_termux_requirements.py --check    # CI mode

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from arena.termux_artifacts import usable_hashes
from arena.termux_validation import validate_closure

if TYPE_CHECKING:
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version
else:
    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:
        from pip._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
        from pip._vendor.packaging.version import InvalidVersion, Version

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "requirements-termux.txt"
OPTIONAL_TARGET = ROOT / "scripts" / "requirements-termux-optional.txt"

# Direct dependencies of the on-device install. `psutil` is optional at
# runtime (every import of it in the bridge is lazy and guarded), but it
# is pinned all the same: optional does not mean unverified.
DIRECT = ("aiohttp",)

# Installed in a SEPARATE pip run. psutil's build backend rejects
# Android outright ("platform android is not supported"), and `pip
# install -r` is all-or-nothing -- keeping it in the main file made its
# failure abort the whole install, aiohttp included. Measured on a POCO
# F7 Pro during the first real on-device install.
OPTIONAL = ("psutil",)

# Transitive closure of aiohttp on Android/CPython. Environment markers
# for other platforms (aiodns, Brotli, backports.zstd -- all excluded on
# sys_platform == "android") are deliberately absent: pinning packages
# that will never be installed there adds noise and rots faster.
#
# `async-timeout` and `typing_extensions` are guarded by python_version
# markers and are included because Termux may ship an older CPython.
TRANSITIVE = (
    "aiohappyeyeballs",
    "aiosignal",
    "async-timeout",
    "attrs",
    "frozenlist",
    "multidict",
    "propcache",
    "typing_extensions",
    "yarl",
    "idna",          # via yarl
)

TIMEOUT_S = 60
# Keep this list in step with the supported-Python matrix in ci.yml. A lock
# accepted by the floor but rejected by a newer supported Termux Python is
# still an unusable lock.
SUPPORTED_PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")


class _PyPIRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.netloc != "pypi.org":
            raise ValueError("only the HTTPS PyPI JSON API is supported")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_pypi(request, timeout):
    # Default handlers retain system/environment proxy settings; the explicit
    # redirect handler enforces the origin restriction on every network hop.
    return urllib.request.build_opener(_PyPIRedirect()).open(request, timeout=timeout)


def _fetch(url: str) -> dict:
    """Fetch JSON from the fixed PyPI host, never an arbitrary URL scheme."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "pypi.org":
        raise ValueError("only the HTTPS PyPI JSON API is supported")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    # Keep urllib's system/environment proxy handling. The origin was checked
    # above; callers supply only PyPI metadata paths, never operator URLs.
    # nosemgrep: dynamic-urllib-use-detected -- exact HTTPS pypi.org origin validated above, preserves HTTPS_PROXY
    with _open_pypi(request, timeout=TIMEOUT_S) as response:  # nosec B310 -- exact HTTPS pypi.org origin validated above
        return json.load(response)


def _relevant(filename: str, packagetype: str) -> bool:
    """Source, universal, and explicitly Android/arm64 artifacts only."""
    return packagetype == "sdist" or (
        packagetype == "bdist_wheel" and _termux_wheel(filename)
    )


def _termux_wheel(filename: str) -> bool:
    """Distinguish portable/Android wheels from glibc-only Linux wheels."""
    lowered = filename.lower()
    platform_tag = lowered.rsplit("-", 1)[-1]
    if lowered.endswith("-none-any.whl"):
        return True
    is_arm64 = "arm64_v8a" in platform_tag or "aarch64" in platform_tag
    return "android_" in platform_tag and is_arm64


def _has_available_artifacts(files: list[dict]) -> bool:
    """A release with no files or only yanked files cannot be installed."""
    return any(not item.get("yanked", False) for item in files)


def _stable_version(value: str) -> Version | None:
    """Parse stable versions without accepting malformed release names."""
    try:
        parsed = Version(value)
    except InvalidVersion:
        return None
    return None if parsed.is_prerelease or parsed.is_devrelease else parsed


def _candidate_versions(releases: dict) -> list[str]:
    """Newest stable releases with at least one non-yanked file."""
    candidates: list[tuple[Version, str]] = []
    for version, files in releases.items():
        if not _has_available_artifacts(files):
            continue
        parsed = _stable_version(version)
        if parsed is not None:
            candidates.append((parsed, version))
    return [version for _, version in sorted(candidates, reverse=True)]


def _supports_python(requires_python: str) -> bool:
    """Whether metadata accepts every Python version in the supported matrix."""
    if not requires_python:
        return True
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return False
    return all(specifier.contains(version)
               for version in SUPPORTED_PYTHON_VERSIONS)


def _usable_hashes(detail: dict) -> list[str]:
    return usable_hashes(detail, SUPPORTED_PYTHON_VERSIONS)


def collect(package: str) -> tuple[str, list[str]]:
    """Return the newest stable usable release and its artifact hashes."""
    project = _fetch(f"https://pypi.org/pypi/{package}/json")
    for version in _candidate_versions(project.get("releases", {})):
        detail = _fetch(f"https://pypi.org/pypi/{package}/{version}/json")
        digests = _usable_hashes(detail)
        if digests:
            return version, digests

    supported = ", ".join(SUPPORTED_PYTHON_VERSIONS)
    raise RuntimeError(
        f"{package}: no non-yanked release with usable artifacts supports "
        f"Python versions {supported}"
    )


OPTIONAL_HEADER = """# OPTIONAL, hash-verified extras for the on-device (Termux) install.
#
# GENERATED FILE -- do not edit by hand.
#     python scripts/refresh_termux_requirements.py
#
# psutil is NOT installable on Android: its build backend refuses the
# platform outright --
#
#     platform android is not supported
#     ERROR: Failed to build 'psutil' when getting requirements to build wheel
#
# measured on a POCO F7 Pro (Android 16, arm64-v8a) during the first
# real on-device install. No wheel exists and the sdist cannot compile,
# so this is a permanent property of the platform.
#
# Separate file because `pip install -r` is all-or-nothing: with psutil
# in the main list its failure took aiohttp down with it and aborted the
# install, even though every psutil import in the bridge is lazy and
# guarded. Optional must mean the install survives without it.
#
# Verified against PyPI on {today}.
"""


def _default_header() -> str:
    return '''# Pinned, hash-verified dependencies for the on-device (Termux) install.
#
# GENERATED FILE -- do not edit by hand.
#     python scripts/refresh_termux_requirements.py
#
# Scorecard alerts #317/#318/#319 flagged `scripts/install_termux.sh`
# for bare `pip install aiohttp` / `pip install psutil`. Unpinned
# installs are a supply-chain hole anywhere; here the artifact lands on
# the operator's phone and is imported by a bridge holding shell access
# on a device that roams between untrusted networks.
#
# `pip install --require-hashes` refuses anything not listed here,
# transitive dependencies included -- which is why they are all present.
#
# Several hashes per package on purpose: Termux/arm64 normally builds
# from the sdist (Bionic matches no manylinux tag), but pip takes a
# wheel when the ABI does match. Omitting the artifact pip actually
# picks would fail the install rather than skip the check.
#
# Verified against PyPI on {today}.
'''


def _render_rows(
    rows: list[tuple[str, str, list[str]]], header: str,
) -> str:
    lines = [header]
    for package, version, digests in rows:
        lines.append(f"\n{package}=={version} \\")
        for index, digest in enumerate(digests):
            suffix = " \\" if index < len(digests) - 1 else ""
            lines.append(f"    --hash=sha256:{digest}{suffix}")
    return "\n".join(lines) + "\n"


def render(rows: list[tuple[str, str, list[str]]], *, header: str | None = None) -> str:
    today = _dt.date.today().isoformat()
    template = _default_header() if header is None else header
    return _render_rows(rows, template.format(today=today))


def _collect_rows(
    packages: tuple[str, ...], *, optional: bool = False,
) -> list[tuple[str, str, list[str]]] | None:
    rows: list[tuple[str, str, list[str]]] = []
    for package in packages:
        try:
            version, digests = collect(package)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            label = "optional " if optional else ""
            print(f"FAILED to resolve {label}{package}: {exc}", file=sys.stderr)
            if not optional:
                print("Nothing written -- a partially generated hash file is "
                      "worse than none.", file=sys.stderr)
            return None
        rows.append((package, version, digests))
        label = "[optional] " if optional else ""
        print(f"  {label}{package}=={version}  ({len(digests)} artifacts)")
    return rows


def _pins(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("# Verified against PyPI on ")]


def _check_current(rendered: str, target: pathlib.Path | None = None) -> int:
    target = TARGET if target is None else target
    if not target.exists():
        print(f"{target} is missing", file=sys.stderr)
        return 1
    # Ignore the generated date; pins must be reproducible across days.
    current = target.read_text(encoding="utf-8")
    if _pins(current) != _pins(rendered):
        print(f"{target.name} is out of date; run "
              "scripts/refresh_termux_requirements.py", file=sys.stderr)
        return 1
    print(f"{target.name} is current")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Regenerate both hash-locked Termux requirements from PyPI; validate "
        "dependency closure and artifact coverage for Python 3.10-3.14. "
        "Install packaging first. --check verifies both files without writing."
    ))
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed file is out of date")
    args = parser.parse_args()
    rows = _collect_rows((*DIRECT, *TRANSITIVE))
    if rows is None:
        return 2
    rendered = render(rows)
    optional_rows = _collect_rows(OPTIONAL, optional=True)
    if optional_rows is None:
        return 2
    try:
        validate_closure(rows, _fetch, SUPPORTED_PYTHON_VERSIONS)
        validate_closure(optional_rows, _fetch, SUPPORTED_PYTHON_VERSIONS, installed=rows)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"FAILED to validate dependency closure: {exc}", file=sys.stderr)
        return 2
    if args.check:
        return max(_check_current(rendered), _check_current(
            render(optional_rows, header=OPTIONAL_HEADER), OPTIONAL_TARGET))
    TARGET.write_text(rendered, encoding="utf-8")
    OPTIONAL_TARGET.write_text(
        render(optional_rows, header=OPTIONAL_HEADER), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    print(f"wrote {OPTIONAL_TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
