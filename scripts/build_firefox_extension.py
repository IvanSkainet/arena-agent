#!/usr/bin/env python3
"""Produce a Firefox-loadable build of the chat extension.

The operator uses Firefox on his phone and asked why the extension is
Chromium-only. Measured against `chat_extension/manifest.json`, three
things make Firefox refuse it outright:

1. **`background.service_worker`.** Firefox implements MV3 background
   as `background.scripts` (an event page). A manifest with only
   `service_worker` loads with no background at all -- and the failure
   is silent, which is worse than an error.

2. **`sidePanel`.** Chromium's side panel API. Firefox has
   `sidebar_action` instead. The permission is unknown to Firefox and
   the whole manifest is rejected.

3. **No `browser_specific_settings.gecko.id`.** Firefox requires an
   extension ID for anything installed outside AMO, including temporary
   loads for development.

Rather than maintain two manifests -- which diverge the first time
someone edits only one -- this generates the Firefox variant from the
Chromium one at build time. The source of truth stays single.

What deliberately is NOT changed: the content scripts, the parser, the
adapters, the host permissions. Those are identical on both engines and
copying them verbatim is the point.

Usage:
    python scripts/build_firefox_extension.py            # build
    python scripts/build_firefox_extension.py --check    # verify only
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "chat_extension"
TARGET = ROOT / "chat_extension_firefox"

# Firefox needs a stable ID for out-of-store installs. Not a secret; it
# only has to be unique and well-formed.
GECKO_ID = "skainet-chat-bridge@skainet.local"

# The oldest Firefox with usable MV3 support.
MIN_FIREFOX = "115.0"

# Chromium-only keys, and what replaces them.
CHROMIUM_ONLY_PERMISSIONS = {"sidePanel"}


def build_manifest(source: dict) -> dict:
    """Translate a Chromium MV3 manifest into a Firefox MV3 manifest."""
    out = json.loads(json.dumps(source))  # deep copy

    # 1. background: service_worker -> scripts
    background = out.get("background") or {}
    worker = background.get("service_worker")
    if worker:
        out["background"] = {"scripts": [worker]}

    # 2. sidePanel -> sidebar_action
    permissions = [p for p in out.get("permissions", [])
                   if p not in CHROMIUM_ONLY_PERMISSIONS]
    out["permissions"] = permissions
    side_panel = out.pop("side_panel", None)
    if side_panel and side_panel.get("default_path"):
        out["sidebar_action"] = {
            "default_panel": side_panel["default_path"],
            "default_title": out.get("name", "Skainet"),
        }

    # 3. the required gecko block
    out["browser_specific_settings"] = {
        "gecko": {"id": GECKO_ID, "strict_min_version": MIN_FIREFOX}
    }

    return out


def verify(manifest: dict) -> list[str]:
    """Everything that would make Firefox reject this. Empty = loadable."""
    problems: list[str] = []
    background = manifest.get("background") or {}
    if "service_worker" in background:
        problems.append("background.service_worker is Chromium-only")
    if not background.get("scripts"):
        problems.append("background.scripts missing: no background page")
    for perm in CHROMIUM_ONLY_PERMISSIONS:
        if perm in manifest.get("permissions", []):
            problems.append(f"{perm!r} permission is Chromium-only")
    if "side_panel" in manifest:
        problems.append("side_panel is Chromium-only (use sidebar_action)")
    gecko = (manifest.get("browser_specific_settings") or {}).get("gecko") or {}
    if not gecko.get("id"):
        problems.append("browser_specific_settings.gecko.id is required")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the generated manifest without writing")
    args = parser.parse_args()

    source_manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    firefox_manifest = build_manifest(source_manifest)

    problems = verify(firefox_manifest)
    if problems:
        print("generated manifest would still be rejected by Firefox:",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if args.check:
        print("firefox manifest is loadable "
              f"({len(firefox_manifest.get('permissions', []))} permissions, "
              f"background: {list((firefox_manifest.get('background') or {}))})")
        return 0

    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET,
                    ignore=shutil.ignore_patterns("*.zip", "__pycache__"))
    (TARGET / "manifest.json").write_text(
        json.dumps(firefox_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(f"wrote {TARGET.relative_to(ROOT)}")
    print("  load it: about:debugging -> This Firefox -> Load Temporary Add-on")
    print(f"  then pick {TARGET.name}/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
