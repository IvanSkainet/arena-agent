"""What kind of machine is the bridge actually running on?

`platform.system()` answers "Linux" on an Android phone, which is true
and useless. Android is a Linux kernel with none of the userland the
rest of this codebase assumes: there is no systemd, no `/etc/passwd`
worth reading, no `~/.config`, and in Termux even the filesystem root
lives under `/data/data/com.termux/files/usr`. Twenty-one call sites
reach for `systemctl`; on a phone every one of them is a lie waiting to
be told.

So the bridge needs to distinguish *host classes*, not just OS names:

    windows | macos | android | linux

and, when it is Android, whether it is running **on the phone itself**
(Termux) or merely talking to one over ADB. Those are completely
different products -- the first has no `adb` and does not need one.

Detection facts, measured on a real device (POCO F7 Pro, Android 16,
SDK 36, arm64-v8a, HyperOS 3) rather than assumed:

    ANDROID_ROOT=/system         set in every Android shell
    ANDROID_DATA=/data           set in every Android shell
    /system/bin/linker64         exists on any 64-bit Android
    PREFIX=/data/data/com.termux/files/usr    set only inside Termux

The order matters. `ANDROID_ROOT` alone is the strongest signal and is
present whether or not Termux is involved; `PREFIX` distinguishes the
Termux userland but is easy for a user to set by accident, so it is
never the sole basis for calling something Android.

Nothing here shells out. This is called during capability reporting and
on startup paths, so it must be fast and must never raise -- a detector
that throws on an unusual machine is worse than one that says "linux".
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

# Host classes the rest of the codebase may branch on.
WINDOWS = "windows"
MACOS = "macos"
ANDROID = "android"
LINUX = "linux"
UNKNOWN = "unknown"

# Termux installs its whole userland under this prefix. Used as a
# corroborating signal, never as the only one.
_TERMUX_PREFIX_MARKER = "com.termux"

# Present in the environment of every Android shell, adb or otherwise.
_ANDROID_ENV_KEYS = ("ANDROID_ROOT", "ANDROID_DATA")

# Filesystem markers, checked only when the environment is inconclusive
# (a stripped service environment can lack the variables above).
_ANDROID_PATH_MARKERS = (
    "/system/bin/linker64",
    "/system/build.prop",
)


def _env_says_android(env: dict[str, str]) -> bool:
    """True when the environment carries Android's own variables.

    Requires ANDROID_ROOT specifically: ANDROID_DATA alone shows up in
    some SDK tooling on desktops, and a false Android verdict on a
    developer laptop would disable systemd handling for no reason.
    """
    root = env.get("ANDROID_ROOT", "")
    return bool(root) and root.startswith("/system")


def _paths_say_android() -> bool:
    for marker in _ANDROID_PATH_MARKERS:
        try:
            if Path(marker).exists():
                return True
        except OSError:
            # A permission error is not a verdict either way.
            continue
    return False


def _is_termux(env: dict[str, str]) -> bool:
    """True when running inside the Termux userland.

    Both PREFIX and TERMUX_VERSION are checked: PREFIX is what actually
    changes behaviour (binaries, config and the package manager all live
    under it) while TERMUX_VERSION confirms intent.
    """
    if _TERMUX_PREFIX_MARKER in env.get("PREFIX", ""):
        return True
    if env.get("TERMUX_VERSION"):
        return True
    return _TERMUX_PREFIX_MARKER in env.get("HOME", "")


def detect_host_class(env: dict[str, str] | None = None,
                      system: str | None = None) -> str:
    """Classify the host. Never raises; falls back to `platform.system()`.

    Both inputs are injectable, and that is not decoration. The first
    version took only `env` and read the real OS internally, so every
    Android case was untestable anywhere except Linux -- ten CI jobs on
    Windows and macOS went red asserting `'macos' == 'android'`, because
    the test could describe a phone's environment but not its operating
    system. A detector that cannot be exercised on the platforms CI runs
    is a detector CI cannot defend.

    `system` takes `platform.system()`-style values ("Linux", "Windows",
    "Darwin"); None means ask the real machine.
    """
    environ = dict(os.environ if env is None else env)
    if system is None:
        # sys.platform is checked too: it is the more reliable signal on
        # frozen builds where platform.system() can be patched away.
        if sys.platform == "win32":
            resolved = "Windows"
        elif sys.platform == "darwin":
            resolved = "Darwin"
        else:
            resolved = platform.system()
    else:
        resolved = system

    # Windows and macOS are unambiguous and cannot be Android.
    if resolved == "Windows":
        return WINDOWS
    if resolved == "Darwin":
        return MACOS

    if _env_says_android(environ):
        return ANDROID
    # Termux alone is corroborating, not conclusive -- but combined with
    # the filesystem markers it is decisive.
    if _is_termux(environ) and _paths_say_android():
        return ANDROID
    if _paths_say_android():
        return ANDROID

    if resolved == "Linux":
        return LINUX
    return UNKNOWN if not resolved else resolved.lower()


def is_android(env: dict[str, str] | None = None,
               system: str | None = None) -> bool:
    return detect_host_class(env, system) == ANDROID


def is_termux(env: dict[str, str] | None = None,
              system: str | None = None) -> bool:
    """Running *inside* Termux on the phone, as opposed to driving one."""
    environ = dict(os.environ if env is None else env)
    return _is_termux(environ) and detect_host_class(environ, system) == ANDROID


def has_systemd(env: dict[str, str] | None = None,
                system: str | None = None) -> bool:
    """Whether `systemctl` is a meaningful thing to invoke here.

    Android has no systemd at all, so 21 call sites that shell out to
    `systemctl` produce a confusing "command not found" instead of an
    honest "not supported on this platform". Checked as a real directory
    rather than the presence of the binary, because a stray `systemctl`
    shim on PATH does not make PID 1 systemd.
    """
    environ = dict(os.environ if env is None else env)
    if detect_host_class(environ, system) != LINUX:
        return False
    try:
        return Path("/run/systemd/system").is_dir()
    except OSError:
        return False


def has_linux_kernel(env: dict[str, str] | None = None,
                     system: str | None = None) -> bool:
    """Whether ``/proc`` and ``/sys`` behave like Linux here.

    Android *is* Linux: ``/proc/modules``, ``/proc/meminfo``,
    ``/proc/stat`` and ``/sys/devices`` all read normally on the phone
    (verified on the POCO F7 Pro, Android 16, aarch64). But fourteen
    probes gated themselves on ``platform.system() == "Linux"``, and
    Python 3.13 on Termux honestly answers ``"Android"`` -- so every one
    of them switched itself off and reported
    ``"kernel modules probe is Linux-only"`` on a machine whose kernel
    modules were sitting right there in ``/proc/modules``.

    That is the wrong axis. ``systemctl`` and ``journalctl`` genuinely
    do not exist on Android -- use :func:`has_systemd` for those. Reading
    ``/proc`` is a different question, and this is it.
    """
    return detect_host_class(env, system) in (LINUX, ANDROID)


def termux_prefix(env: dict[str, str] | None = None) -> str | None:
    """Termux's `$PREFIX`, or None when not in Termux."""
    environ = dict(os.environ if env is None else env)
    if not _is_termux(environ):
        return None
    prefix = environ.get("PREFIX", "")
    if _TERMUX_PREFIX_MARKER in prefix:
        return prefix
    return f"/data/data/{_TERMUX_PREFIX_MARKER}/files/usr"


def describe(env: dict[str, str] | None = None,
             system: str | None = None) -> dict[str, Any]:
    """A JSON-safe summary for `/v1/capabilities` and the dashboard."""
    environ = dict(os.environ if env is None else env)
    host_class = detect_host_class(environ, system)
    summary: dict[str, Any] = {
        "class": host_class,
        "system": platform.system(),
        "machine": platform.machine(),
        "termux": is_termux(environ, system),
        "systemd": has_systemd(environ, system),
    }
    if host_class == ANDROID:
        summary["android_root"] = environ.get("ANDROID_ROOT") or None
        summary["termux_prefix"] = termux_prefix(environ)
        # Distinguishing the two Android products is the whole point:
        # on-device means the bridge IS the phone.
        summary["role"] = "on-device" if summary["termux"] else "android-host"
    return summary
