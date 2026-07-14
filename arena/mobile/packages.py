"""Package inventory via `adb shell pm list packages`.

Phase 1 scope: read-only listing. No install / uninstall / permission
grants — those need a separate design pass with explicit user consent
per install source.
"""
from __future__ import annotations

from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run


def list_packages(
    serial: str,
    *,
    filter_text: str | None = None,
    include_system: bool = True,
    include_disabled: bool = False,
) -> dict[str, Any]:
    """Return every package name visible to `adb shell pm list packages`.

    * `filter_text` — optional substring filter (case-sensitive; matches
      `pm list packages`'s own -f semantics).
    * `include_system` — when False, add `-3` to restrict to third-party.
    * `include_disabled` — when False, add `-e` to restrict to enabled.
    """
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    args = ["shell", "pm", "list", "packages"]
    if not include_system:
        args.append("-3")
    if not include_disabled:
        args.append("-e")
    if filter_text:
        if not isinstance(filter_text, str):
            return {"ok": False, "error": "filter_text must be a string"}
        # Very light sanitisation: reject shell metachars just like shell.py does.
        for ch in (";", "&", "|", "`", "$", ">", "<", "\n", "\r"):
            if ch in filter_text:
                return {"ok": False, "error": f"filter_text contains disallowed char: {ch!r}"}
        args.append(filter_text)

    try:
        r = run(args, serial=serial, timeout=30)
    except AdbNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"pm list packages failed: {e}"}

    if r.returncode != 0:
        return {
            "ok": False,
            "error": (r.stderr or f"pm exit {r.returncode}").strip(),
            "stdout": r.stdout,
            "stderr": r.stderr,
        }

    packages = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        packages.append(line[len("package:"):].strip())

    return {
        "ok": True,
        "serial": serial,
        "packages": packages,
        "count": len(packages),
        "filter": filter_text,
        "include_system": include_system,
        "include_disabled": include_disabled,
    }
