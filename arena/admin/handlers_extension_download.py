"""Serve the browser extension as a ZIP, straight from the running bridge.

The operator's report: *"I can't install the extension yet, the needed
files aren't there. Installing through Termux is really inconvenient."*

Two separate problems behind one sentence, and both are ours:

**The files genuinely were not there.** `chat_extension_firefox` shipped
inside the v4.169.0 release zip and never reached his disk, because
auto-update copies a hand-maintained list of directory names and nobody
added it. Measured on his machine: `chat_extension` 18 files,
`chat_extension_firefox` MISSING. Worse, `chat_extension` was absent
from that list too -- so the extension had never been updated by
auto-update at all, only by a fresh install. Fixed in `auto_update.py`.

**Even with the files present, getting them is awkward.** On a phone
they sit inside Termux's private directory tree. Firefox for Android
cannot browse there, and telling someone to `cp -r` into
`~/storage/downloads` is exactly the kind of instruction that made him
say Termux is inconvenient.

So the bridge hands them over itself. `GET /v1/extension/download`
returns a ZIP the browser can save, built in memory from the install
root. No file manager, no shell, no knowing where anything lives.

`?browser=firefox` picks the Firefox build; anything else gets the
Chromium one. If the Firefox directory is missing -- an install that
predates it -- the manifest is generated on the fly rather than
returning a 404, because "the file you need does not exist on this
machine" is not an answer the operator can act on.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.handler_helpers import authed

CHROMIUM_DIR = "chat_extension"
FIREFOX_DIR = "chat_extension_firefox"

# Files that must never leave the machine even if someone drops them in
# the extension directory while debugging.
EXCLUDED_NAMES = frozenset({"token.txt", ".env", "secrets.json"})
EXCLUDED_SUFFIXES = (".log", ".pyc", ".zip")


def _install_root() -> Path:
    from arena.constants import BRIDGE_DIR
    return Path(BRIDGE_DIR)


def _iter_files(source: Path):
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if path.name.endswith(EXCLUDED_SUFFIXES):
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def _firefox_manifest(chromium_manifest: dict[str, Any]) -> dict[str, Any]:
    """Translate on the fly when no prebuilt Firefox directory exists.

    Same three transforms as `scripts/build_firefox_extension.py`:
    service_worker -> scripts, sidePanel -> sidebar_action, and the
    required gecko id. Duplicated deliberately and kept small -- the
    alternative is importing a build script into a request handler.
    """
    out = json.loads(json.dumps(chromium_manifest))
    background = out.get("background") or {}
    worker = background.get("service_worker")
    if worker:
        out["background"] = {"scripts": [worker]}
    out["permissions"] = [p for p in out.get("permissions", [])
                          if p != "sidePanel"]
    side_panel = out.pop("side_panel", None)
    if side_panel and side_panel.get("default_path"):
        out["sidebar_action"] = {
            "default_panel": side_panel["default_path"],
            "default_title": out.get("name", "Skainet Chat Bridge"),
        }
    out["browser_specific_settings"] = {
        "gecko": {"id": "skainet-chat-bridge@skainet.local",
                  "strict_min_version": "115.0"}
    }
    return out


def build_zip(root: Path, *, firefox: bool) -> tuple[bytes, str, dict[str, Any]]:
    """Return (zip bytes, filename, diagnostic info)."""
    chromium = root / CHROMIUM_DIR
    if not chromium.is_dir():
        raise FileNotFoundError(
            f"{CHROMIUM_DIR} is not present in {root}. The install is "
            f"incomplete -- re-run the installer or update the bridge."
        )

    prebuilt = root / FIREFOX_DIR
    source = prebuilt if (firefox and prebuilt.is_dir()) else chromium
    generated_manifest = None
    if firefox and not prebuilt.is_dir():
        # Older install: no Firefox directory on disk. Build the manifest
        # here rather than refusing -- the operator cannot act on "that
        # folder does not exist on your machine".
        generated_manifest = _firefox_manifest(
            json.loads((chromium / "manifest.json").read_text(encoding="utf-8")))

    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _iter_files(source):
            relative = path.relative_to(source).as_posix()
            if generated_manifest is not None and relative == "manifest.json":
                archive.writestr(relative, json.dumps(
                    generated_manifest, indent=2, ensure_ascii=False) + "\n")
            else:
                archive.write(path, relative)
            count += 1

    name = "skainet-extension-firefox.zip" if firefox else "skainet-extension.zip"
    info = {
        "source": source.name,
        "files": count,
        "manifest_generated": generated_manifest is not None,
    }
    return buffer.getvalue(), name, info


def make_extension_download_handlers(ctx):
    @authed(ctx)
    async def handle_download(request: web.Request) -> web.Response:
        browser = (request.query.get("browser") or "").strip().lower()
        firefox = browser in ("firefox", "gecko", "ff")
        try:
            payload, filename, info = build_zip(_install_root(), firefox=firefox)
        except FileNotFoundError as exc:
            return ctx.cors_json_response({"ok": False, "error": str(exc)},
                                          status=404)
        except OSError as exc:
            return ctx.cors_json_response(
                {"ok": False, "error": f"could not build the archive: {exc}"},
                status=500)

        ctx.audit({"type": "extension.download", "browser": browser or "chromium",
                   "files": info["files"],
                   "manifest_generated": info["manifest_generated"]})
        return web.Response(
            body=payload,
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{filename}"',
                # Handy for scripted callers and for the Dashboard to show
                # what it just handed over.
                "X-Arena-Extension-Files": str(info["files"]),
                "X-Arena-Extension-Source": info["source"],
            },
        )

    @authed(ctx)
    async def handle_status(request: web.Request) -> web.Response:
        """What is installable from this machine, and how."""
        root = _install_root()
        chromium = (root / CHROMIUM_DIR)
        firefox = (root / FIREFOX_DIR)
        chromium_files = len(list(_iter_files(chromium))) if chromium.is_dir() else 0
        firefox_files = len(list(_iter_files(firefox))) if firefox.is_dir() else 0
        return ctx.cors_json_response({
            "ok": chromium_files > 0,
            "chromium": {"present": chromium.is_dir(), "files": chromium_files,
                         "download": "/v1/extension/download"},
            "firefox": {
                "present": firefox.is_dir(),
                "files": firefox_files,
                "download": "/v1/extension/download?browser=firefox",
                "note": (None if firefox.is_dir() else
                         "No prebuilt Firefox directory on this install; the "
                         "download will generate a Firefox manifest on the fly."),
            },
            "install_hint": {
                "chromium": "Unzip, then chrome://extensions -> Developer mode "
                            "-> Load unpacked.",
                "firefox": "Unzip, then about:debugging#/runtime/this-firefox "
                           "-> Load Temporary Add-on -> pick manifest.json.",
                "android_firefox": "Firefox for Android cannot side-load "
                                   "extensions from a file; it installs them "
                                   "from addons.mozilla.org only. Use the "
                                   "Dashboard in the phone's browser instead "
                                   "-- it needs no extension.",
            },
        })

    return {"download": handle_download, "status": handle_status}
