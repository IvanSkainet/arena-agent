"""Declarative table of Android emulator managers.

A provider is *data*: where its CLI usually lives, and which argv shapes
list / start / stop an instance. No provider gets bespoke Python. If a
manager cannot be expressed as a few argv templates it does not belong
here -- it belongs in a user-built tool via ``tool_foundry``.

Placeholders inside argv templates:

``{id}``
    Instance identifier, as reported by the provider's own list output.

Templates that need no instance simply omit the placeholder.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Environment variable carrying extra/override providers as a JSON array.
# Each element uses the same keys as EmulatorProvider fields. This is the
# supported way to teach the bridge about an emulator we have never heard
# of without shipping code for it.
PROVIDERS_ENV = "ARENA_EMULATOR_PROVIDERS"


@dataclass(frozen=True)
class EmulatorProvider:
    """One emulator manager, described entirely by data."""

    id: str
    label: str
    # Which host OSes this manager can run on. platform.system().lower()
    # values: "windows", "linux", "darwin". Empty means "any".
    os: tuple[str, ...] = ()
    # Executable names to look for on PATH, in preference order.
    binary_names: tuple[str, ...] = ()
    # Environment variable that pins an absolute path to the CLI.
    binary_env: str = ""
    # Absolute paths to probe when PATH lookup fails. May contain
    # ``$ENVVAR`` / ``%ENVVAR%`` style references, expanded at probe time.
    well_known: tuple[str, ...] = ()
    # argv tails (the binary is prepended). Empty tuple = unsupported op.
    list_argv: tuple[str, ...] = ()
    start_argv: tuple[str, ...] = ()
    stop_argv: tuple[str, ...] = ()
    docs: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "os": list(self.os),
            "binary_names": list(self.binary_names),
            "binary_env": self.binary_env,
            "well_known": list(self.well_known),
            "list_argv": list(self.list_argv),
            "start_argv": list(self.start_argv),
            "stop_argv": list(self.stop_argv),
            "docs": self.docs,
            "notes": self.notes,
        }


BUILTIN_PROVIDERS: tuple[EmulatorProvider, ...] = (
    EmulatorProvider(
        id="avd",
        label="Android Emulator (AOSP / Android Studio AVD)",
        os=("windows", "linux", "darwin"),
        binary_names=("emulator",),
        binary_env="ANDROID_EMULATOR",
        well_known=(
            "$ANDROID_HOME/emulator/emulator",
            "$ANDROID_SDK_ROOT/emulator/emulator",
            "$HOME/Android/Sdk/emulator/emulator",
            "$HOME/Library/Android/sdk/emulator/emulator",
            "%LOCALAPPDATA%\\Android\\Sdk\\emulator\\emulator.exe",
        ),
        list_argv=("-list-avds",),
        start_argv=("-avd", "{id}"),
        # The AOSP emulator has no stop verb; shut down over ADB instead.
        stop_argv=(),
        docs="https://developer.android.com/studio/run/emulator-commandline",
        notes="Reference provider: ships with the Android SDK on every OS.",
    ),
    EmulatorProvider(
        id="genymotion",
        label="Genymotion Desktop",
        os=("windows", "linux", "darwin"),
        binary_names=("gmtool",),
        binary_env="GMTOOL_PATH",
        well_known=(
            "/Applications/Genymotion.app/Contents/MacOS/gmtool",
            "$HOME/genymotion/gmtool",
            "%ProgramFiles%\\Genymobile\\Genymotion\\gmtool.exe",
        ),
        list_argv=("admin", "list"),
        start_argv=("admin", "start", "{id}"),
        stop_argv=("admin", "stop", "{id}"),
        docs="https://docs.genymotion.com/desktop/",
    ),
    EmulatorProvider(
        id="mumu",
        label="MuMu Player",
        os=("windows",),
        binary_names=("mumu-cli",),
        binary_env="ARENA_MUMU_CLI",
        well_known=(
            "%ProgramFiles%\\Netease\\MuMuPlayer\\nx_main\\mumu-cli.exe",
            "%ProgramFiles(x86)%\\Netease\\MuMuPlayer\\nx_main\\mumu-cli.exe",
        ),
        list_argv=("info", "--vmindex", "all"),
        start_argv=("control", "--vmindex", "{id}", "launch"),
        stop_argv=("control", "--vmindex", "{id}", "shutdown"),
        docs="https://www.mumuplayer.com/",
        notes="Windows-only vendor CLI; instance ids are numeric vmindexes.",
    ),
    EmulatorProvider(
        id="waydroid",
        label="Waydroid (Linux container)",
        os=("linux",),
        binary_names=("waydroid",),
        binary_env="WAYDROID_PATH",
        well_known=("/usr/bin/waydroid",),
        list_argv=("status",),
        start_argv=("session", "start"),
        stop_argv=("session", "stop"),
        docs="https://docs.waydro.id/",
        notes="Single session; instance id is ignored.",
    ),
)


def _expand(raw: str) -> str:
    """Expand both ``$VAR``/``${VAR}`` and ``%VAR%`` forms, then ``~``."""
    return str(Path(os.path.expandvars(os.path.expanduser(raw))))


def _coerce(entry: Any) -> EmulatorProvider | None:
    """Build a provider from a JSON object, ignoring unknown keys.

    Returns None when the entry is unusable. Malformed host configuration
    must never take the bridge down, but it must also never silently
    produce a half-built provider that fails later at argv time.
    """
    if not isinstance(entry, dict):
        return None
    pid = str(entry.get("id") or "").strip()
    if not pid:
        return None

    def _tup(key: str) -> tuple[str, ...]:
        val = entry.get(key) or ()
        if isinstance(val, str):
            return (val,)
        if isinstance(val, (list, tuple)):
            return tuple(str(x) for x in val)
        return ()

    return EmulatorProvider(
        id=pid,
        label=str(entry.get("label") or pid),
        os=tuple(x.lower() for x in _tup("os")),
        binary_names=_tup("binary_names"),
        binary_env=str(entry.get("binary_env") or ""),
        well_known=_tup("well_known"),
        list_argv=_tup("list_argv"),
        start_argv=_tup("start_argv"),
        stop_argv=_tup("stop_argv"),
        docs=str(entry.get("docs") or ""),
        notes=str(entry.get("notes") or ""),
    )


def load_providers() -> list[EmulatorProvider]:
    """Return builtin providers merged with host-declared ones.

    A host entry sharing an id with a builtin *replaces* it, so an operator
    can correct a wrong well-known path without a code change.
    """
    merged: dict[str, EmulatorProvider] = {p.id: p for p in BUILTIN_PROVIDERS}
    raw = os.environ.get(PROVIDERS_ENV, "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for entry in parsed:
                prov = _coerce(entry)
                if prov is not None:
                    merged[prov.id] = prov
    return list(merged.values())


def resolve_binary(provider: EmulatorProvider) -> str | None:
    """Locate the provider's CLI on this host, or return None.

    Order: explicit env pin, then PATH, then well-known absolute paths.
    A pinned path that does not exist is *not* silently skipped -- it is
    skipped for resolution but reported by :func:`detect_providers` as a
    broken pin, because a typo in an env var is exactly the kind of thing
    that otherwise looks like "the emulator is not installed".
    """
    if provider.binary_env:
        pinned = os.environ.get(provider.binary_env, "").strip()
        if pinned:
            path = _expand(pinned)
            if os.path.isfile(path):
                return path

    for name in provider.binary_names:
        found = shutil.which(name)
        if found:
            return found

    for raw in provider.well_known:
        path = _expand(raw)
        # An unexpanded %VAR% or $VAR means the variable is absent on this
        # host; the path is meaningless, so skip it rather than stat it.
        if "%" in path or "$" in path:
            continue
        if os.path.isfile(path):
            return path
    return None


def detect_providers(*, host_os: str | None = None) -> list[dict[str, Any]]:
    """Describe every known provider and whether it is usable here."""
    system = (host_os or platform.system()).lower()
    out: list[dict[str, Any]] = []
    for provider in load_providers():
        supported = (not provider.os) or (system in provider.os)
        binary = resolve_binary(provider) if supported else None
        pinned = os.environ.get(provider.binary_env, "").strip() if provider.binary_env else ""
        broken_pin = bool(pinned) and not os.path.isfile(_expand(pinned))
        row = {
            "id": provider.id,
            "label": provider.label,
            "supported_on_host": supported,
            "available": binary is not None,
            "binary": binary,
            "host_os": system,
            "supports": {
                "list": bool(provider.list_argv),
                "start": bool(provider.start_argv),
                "stop": bool(provider.stop_argv),
            },
            "docs": provider.docs,
            "notes": provider.notes,
        }
        if broken_pin:
            row["binary_env"] = provider.binary_env
            row["broken_pin"] = pinned
            row["hint"] = (
                f"{provider.binary_env} points at {pinned!r}, which is not a file. "
                "Fix or unset it; detection fell back to PATH and well-known paths."
            )
        elif supported and binary is None:
            row["hint"] = f"{provider.label} CLI not found on this host. See {provider.docs}" if provider.docs else f"{provider.label} CLI not found on this host."
        out.append(row)
    return out


def find_provider(provider_id: str) -> EmulatorProvider | None:
    for provider in load_providers():
        if provider.id == provider_id:
            return provider
    return None


def build_argv(provider: EmulatorProvider, template: tuple[str, ...], instance: str) -> list[str]:
    """Substitute ``{id}`` into an argv template. No shell, ever."""
    return [part.replace("{id}", instance) for part in template]


__all__ = [
    "BUILTIN_PROVIDERS",
    "PROVIDERS_ENV",
    "EmulatorProvider",
    "build_argv",
    "detect_providers",
    "find_provider",
    "load_providers",
    "resolve_binary",
]
