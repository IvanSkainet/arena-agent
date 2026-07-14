"""ADB binary discovery + safe command runner for the Arena mobile domain.

Cross-platform: works out of the box on Windows/macOS/Linux without any
platform-specific installer helpers. Looks up `adb` in the following
order:

  1. `ADB_PATH` environment variable (explicit override).
  2. `adb` (or `adb.exe`) on PATH.
  3. Platform-specific well-known install locations:
      * Windows: Android SDK under %LOCALAPPDATA%\\Android\\Sdk\\platform-tools,
                 %ProgramFiles%\\Android\\..., scoop/chocolatey paths.
      * macOS:   Homebrew (Intel + Apple Silicon), Android Studio's SDK.
      * Linux:   /opt/android-sdk/platform-tools, /usr/bin, /usr/local/bin.

Never invokes sudo. Never assumes Linux. On Windows we always spawn
adb with CREATE_NO_WINDOW so a `/v1/mobile/devices` poll does not flash
a CMD window on every refresh — same lesson as ZeroTier.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Same trick as arena/admin/zerotier.py — hide the console window on Windows.
_SUBPROCESS_KWARGS: dict[str, Any] = {}
if platform.system().lower() == "windows":
    _SUBPROCESS_KWARGS["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# Default timeouts, overridable per call. adb operations that touch the
# device (shell, screencap, input) can be slow on cold-USB or after phone
# lock — keep the default generous but not unbounded.
DEFAULT_TIMEOUT = 15


def _candidates() -> list[str]:
    """Return every well-known adb location, ordered by preference."""
    system = platform.system().lower()
    home = Path.home()
    names = ["adb.exe", "adb"] if system == "windows" else ["adb"]

    paths: list[str] = []

    # 1) Explicit env override.
    override = os.environ.get("ADB_PATH")
    if override:
        paths.append(override)

    # 2) PATH lookup.
    for name in names:
        found = shutil.which(name)
        if found:
            paths.append(found)

    # 3) Well-known locations per platform.
    if system == "windows":
        localappdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        paths += [
            os.path.join(localappdata, "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(program_files, "Android", "android-sdk", "platform-tools", "adb.exe"),
            os.path.join(program_files_x86, "Android", "android-sdk", "platform-tools", "adb.exe"),
            # scoop
            os.path.join(str(home), "scoop", "apps", "adb", "current", "adb.exe"),
            # chocolatey
            r"C:\ProgramData\chocolatey\lib\adb\tools\platform-tools\adb.exe",
        ]
    elif system == "darwin":
        paths += [
            "/opt/homebrew/bin/adb",
            "/usr/local/bin/adb",
            str(home / "Library" / "Android" / "sdk" / "platform-tools" / "adb"),
            "/Applications/Android Studio.app/Contents/plugins/Android/lib/android-tools/adb",
        ]
    else:  # Linux / *BSD
        paths += [
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            "/opt/android-sdk/platform-tools/adb",
            "/opt/android-sdk-linux/platform-tools/adb",
            str(home / "Android" / "Sdk" / "platform-tools" / "adb"),
            str(home / ".local" / "share" / "android-sdk" / "platform-tools" / "adb"),
        ]

    # Dedup while keeping order, drop anything that isn't a real executable.
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            out.append(p)
    return out


def find_adb() -> str | None:
    """Return the first usable adb path, or None if none found."""
    cands = _candidates()
    return cands[0] if cands else None


def _install_hint() -> str:
    system = platform.system().lower()
    if system == "windows":
        return (
            "Install Android Platform Tools: `winget install --id Google.PlatformTools` "
            "or `scoop install adb`. Docs: "
            "https://developer.android.com/tools/releases/platform-tools"
        )
    if system == "darwin":
        return (
            "Install Android Platform Tools: `brew install --cask android-platform-tools`. "
            "Docs: https://developer.android.com/tools/releases/platform-tools"
        )
    return (
        "Install Android Platform Tools, e.g. `sudo pacman -S android-tools` on Arch/CachyOS, "
        "or `sudo apt install android-tools-adb` on Debian/Ubuntu. Docs: "
        "https://developer.android.com/tools/releases/platform-tools"
    )


def install_hint() -> str:
    """Public wrapper — same platform-specific install command as the tests use."""
    return _install_hint()


class AdbNotFoundError(RuntimeError):
    """Raised when we cannot locate an adb binary on this host."""


def run(
    args: list[str],
    *,
    serial: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    input_bytes: bytes | None = None,
    capture_binary: bool = False,
    no_route: bool = False,
) -> subprocess.CompletedProcess:
    """Run `adb [-s <serial>] <args...>` and return the CompletedProcess.

    * `serial` — target a specific device by its ADB serial. When None the
      command targets the "any" device, which is unambiguous only when
      exactly one device is connected.
    * `capture_binary` — when True, stdout is captured as bytes (needed by
      screenshot which pulls raw PNG data). Otherwise stdout+stderr are
      captured as text.

    v3.84.5: transparently routes through the transport registry in
    `arena.mobile.adb_fallback`. If a wireless-ADB alias is registered
    for `serial` and the USB primary trips the circuit breaker, subsequent
    calls flow through the alias until the primary recovers. Callers that
    never register a fallback see identical behaviour to prior releases.
    """
    adb = find_adb()
    if adb is None:
        raise AdbNotFoundError(install_hint())

    # Route through the fallback registry before spawning adb. When
    # `serial` is None we skip routing entirely -- the "no serial" path
    # is only unambiguous with exactly one device, and swapping it out
    # would be surprising. Callers that MUST hit a specific transport
    # (transport.enable_tcp doing `adb -s <usb> tcpip 5555`) pass
    # `no_route=True` to opt out.
    effective = serial
    canonical = serial
    if serial and not no_route:
        try:
            from arena.mobile import adb_fallback as _fb
            effective = _fb.pick_transport(serial)
        except Exception:
            # Registry is optional; a broken import must never crash a call.
            effective = serial

    cmd: list[str] = [adb]
    if effective:
        cmd += ["-s", effective]
    cmd += args

    kwargs: dict[str, Any] = {"timeout": timeout, **_SUBPROCESS_KWARGS}
    if capture_binary:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    else:
        kwargs["capture_output"] = True
        kwargs["text"] = True

    if input_bytes is not None:
        kwargs["input"] = input_bytes
    result = subprocess.run(cmd, **kwargs)

    # Feed the outcome back to the registry so subsequent calls can
    # route around a failing transport. stderr may be str or bytes
    # depending on `capture_binary`.
    if canonical and not no_route:
        try:
            from arena.mobile import adb_fallback as _fb
            raw_err = result.stderr or ""
            if isinstance(raw_err, (bytes, bytearray)):
                raw_err = raw_err.decode("utf-8", "replace")
            _fb.record_outcome(canonical, effective or canonical,
                               returncode=result.returncode,
                               stderr=raw_err)
        except Exception:
            pass
    return result


def adb_version() -> str | None:
    """Return the `adb version` short string, or None if adb is missing."""
    try:
        r = run(["version"], timeout=5)
    except (AdbNotFoundError, subprocess.TimeoutExpired):
        return None
    text = (r.stdout or "") + " " + (r.stderr or "")
    # e.g. "Android Debug Bridge version 1.0.41"
    import re as _re
    m = _re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", text)
    return m.group(1) if m else text.strip().splitlines()[0][:100] or None
