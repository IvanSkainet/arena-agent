#!/usr/bin/env python3
"""Regenerate the hash-pinned requirements file for the Termux install.

Scorecard alerts #317/#318/#319 flagged `scripts/install_termux.sh` for
running bare `pip install aiohttp` / `pip install psutil`. Unpinned is
bad anywhere; it is worse here, because the package lands on the
operator's *phone* and the bridge that imports it runs with shell
access on a device that roams between untrusted networks.

The fix is `pip install --require-hashes -r scripts/requirements-termux.txt`,
which needs every artifact -- including transitive dependencies --
listed with its digest. Maintaining that by hand rots immediately, so
this script rebuilds it from PyPI.

Two deliberate choices:

* **Hashes for several artifacts per package.** Termux on arm64 usually
  builds `aiohttp` from the sdist because no manylinux wheel matches its
  Bionic libc, but pip will happily take a wheel when the ABI *does*
  match. A hash set that omits the artifact pip actually chooses makes
  the install fail rather than silently skip the check -- so both the
  sdist and the aarch64 / pure-Python wheels are recorded.

* **Refuses to write a file it could not verify.** If any package or
  version cannot be resolved, nothing is written. A half-generated
  requirements file that happens to satisfy pip is exactly the kind of
  quiet failure this whole exercise is against.

Usage:
    python scripts/refresh_termux_requirements.py            # rewrite
    python scripts/refresh_termux_requirements.py --check    # CI mode
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

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


def _fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def _relevant(filename: str, packagetype: str) -> bool:
    """Artifacts pip could plausibly pick on Termux/arm64."""
    if packagetype == "sdist":
        return True
    lowered = filename.lower()
    return ("aarch64" in lowered
            or lowered.endswith("-none-any.whl")
            or "py3-none-any" in lowered)


def collect(package: str) -> tuple[str, list[str]]:
    """Return (version, sorted hashes) for the newest release."""
    data = _fetch(f"https://pypi.org/pypi/{package}/json")
    version = data["info"]["version"]
    detail = _fetch(f"https://pypi.org/pypi/{package}/{version}/json")
    digests = {
        entry["digests"]["sha256"]
        for entry in detail["urls"]
        if _relevant(entry["filename"], entry["packagetype"])
    }
    if not digests:
        raise RuntimeError(f"{package}=={version}: no usable artifact found")
    return version, sorted(digests)


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


def render(rows: list[tuple[str, str, list[str]]], *, header: str | None = None) -> str:
    today = _dt.date.today().isoformat()
    if header is not None:
        lines = [header.format(today=today)]
        for package, version, digests in rows:
            lines.append(f"\n{package}=={version} \\")
            for index, digest in enumerate(digests):
                suffix = " \\" if index < len(digests) - 1 else ""
                lines.append(f"    --hash=sha256:{digest}{suffix}")
        return "\n".join(lines) + "\n"
    header = f'''# Pinned, hash-verified dependencies for the on-device (Termux) install.
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
    lines = [header]
    for package, version, digests in rows:
        lines.append(f"\n{package}=={version} \\")
        for index, digest in enumerate(digests):
            suffix = " \\" if index < len(digests) - 1 else ""
            lines.append(f"    --hash=sha256:{digest}{suffix}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed file is out of date")
    args = parser.parse_args()

    rows: list[tuple[str, str, list[str]]] = []
    for package in (*DIRECT, *TRANSITIVE):
        try:
            version, digests = collect(package)
        except (urllib.error.URLError, KeyError, RuntimeError) as exc:
            print(f"FAILED to resolve {package}: {exc}", file=sys.stderr)
            print("Nothing written -- a partially generated hash file is "
                  "worse than none.", file=sys.stderr)
            return 2
        rows.append((package, version, digests))
        print(f"  {package}=={version}  ({len(digests)} artifacts)")

    rendered = render(rows)

    if args.check:
        if not TARGET.exists():
            print(f"{TARGET} is missing", file=sys.stderr)
            return 1
        # Compare the pins, not the date header: a refresh run on a
        # different day must not fail CI on its own.
        def pins(text: str) -> list[str]:
            return [ln.strip() for ln in text.splitlines()
                    if ln.strip().startswith(("--hash=", ))
                    or ("==" in ln and not ln.lstrip().startswith("#"))]
        if pins(TARGET.read_text(encoding="utf-8")) != pins(rendered):
            print("requirements-termux.txt is out of date; run "
                  "scripts/refresh_termux_requirements.py", file=sys.stderr)
            return 1
        print("requirements-termux.txt is current")
        return 0

    optional_rows: list[tuple[str, str, list[str]]] = []
    for package in OPTIONAL:
        try:
            version, digests = collect(package)
        except (urllib.error.URLError, KeyError, RuntimeError) as exc:
            print(f"FAILED to resolve optional {package}: {exc}", file=sys.stderr)
            return 2
        optional_rows.append((package, version, digests))
        print(f"  [optional] {package}=={version}  ({len(digests)} artifacts)")

    TARGET.write_text(rendered, encoding="utf-8")
    OPTIONAL_TARGET.write_text(
        render(optional_rows, header=OPTIONAL_HEADER), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    print(f"wrote {OPTIONAL_TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
