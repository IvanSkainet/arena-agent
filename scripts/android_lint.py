#!/usr/bin/env python3
"""Gate: the Android app must not repeat the sandbox mistakes it already made.

CI cannot install an APK on a phone, and pretending otherwise would be
worse than nothing. What it *can* do is refuse the two designs that were
already built, shipped to the device, and proven impossible there:

1. **Executing Termux's binaries.** The first BridgeService launched
   `/data/data/com.termux/files/usr/bin/python3` through ProcessBuilder.
   Android's per-app sandbox forbids it. Every check returned false and
   the UI announced "Termux installed: no" on a phone that was running
   Termux and serving the bridge.

2. **Stat-ing another app's data directory.** Same root cause, different
   symptom: a `File` under `/data/data/com.termux` always reports absent,
   so the answer looks like a fact and is actually a permission error.

Neither mistake is detectable by javac, both cost a build-install-screenshot
round trip, and both are one careless edit away from returning.

It also checks the things that silently disable the app: a missing
`<queries>` block makes the honest package-manager lookup fail the same
way the file check did, and a missing `foregroundServiceType` makes
Android 34 refuse to start the service at all.

Runs without a JDK or an SDK, so it belongs in the normal test lane
rather than a special Android job.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android_app"
SRC = APP / "src"
MANIFEST = APP / "AndroidManifest.xml"

MIN_JAVA_FILES = 4

FORBIDDEN_CALLS = (
    ("ProcessBuilder", "cannot execute another app's binaries (per-app sandbox)"),
    ("Runtime.getRuntime().exec", "cannot execute another app's binaries"),
)

REQUIRED_PERMISSIONS = (
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
    "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
    "android.permission.RECEIVE_BOOT_COMPLETED",
    "android.permission.WAKE_LOCK",
)


def _strip_java_comments(text: str) -> str:
    """Remove comments so the gate cannot flag its own explanations.

    Three releases running, a gate caught the prose describing the bug it
    was written for (psutil, download&, control_status). The sources here
    document both forbidden approaches at length, on purpose.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _strip_xml_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def check() -> tuple[list[str], int]:
    problems: list[str] = []
    if not APP.is_dir():
        raise SystemExit(f"android lint: app directory missing: {APP}")
    if not MANIFEST.is_file():
        raise SystemExit(f"android lint: manifest missing: {MANIFEST}")

    java_files = sorted(SRC.rglob("*.java"))
    scanned = len(java_files)

    for path in java_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        code = _strip_java_comments(path.read_text(encoding="utf-8"))
        for needle, why in FORBIDDEN_CALLS:
            if needle in code:
                problems.append(f"{rel}: {needle} -- {why}")
        if "/data/data/com.termux" in code:
            problems.append(
                f"{rel}: references another app's data directory; the sandbox "
                f"answers 'absent' for every path under it, which reads as a "
                f"fact and is a permission error"
            )

    manifest = _strip_xml_comments(MANIFEST.read_text(encoding="utf-8"))

    for perm in REQUIRED_PERMISSIONS:
        if perm not in manifest:
            problems.append(f"AndroidManifest.xml: missing {perm}")

    if "<queries>" not in manifest or 'android:name="com.termux"' not in manifest:
        problems.append(
            "AndroidManifest.xml: no <queries> entry for com.termux -- on "
            "Android 11+ getPackageInfo then throws and the app reports "
            "'Termux installed: no' on a phone that has it"
        )
    if "QUERY_ALL_PACKAGES" in manifest:
        problems.append(
            "AndroidManifest.xml: QUERY_ALL_PACKAGES is a blanket permission; "
            "declare the one package we integrate with instead"
        )
    if 'android:foregroundServiceType="specialUse"' not in manifest:
        problems.append(
            "AndroidManifest.xml: the service needs a foregroundServiceType; "
            "Android 34 refuses to start one without it"
        )
    if "BOOT_COMPLETED" not in manifest:
        problems.append("AndroidManifest.xml: no BOOT_COMPLETED receiver")

    return problems, scanned


def main() -> int:
    problems, scanned = check()
    if scanned < MIN_JAVA_FILES:
        print(f"android lint: FAIL -- scanned only {scanned} java files "
              f"(expected at least {MIN_JAVA_FILES}); the scan is broken, "
              f"not the app clean")
        return 1
    if problems:
        print("android lint: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(f"android lint: OK ({scanned} java files, manifest checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
