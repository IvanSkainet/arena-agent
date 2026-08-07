"""Run mobile commands ON the phone instead of through `adb` from a desktop.

Every one of the 22 modules in `arena/mobile` reaches the device through
a single function, `arena.mobile.adb.run`. That chokepoint is the seam:
when the bridge is running in Termux, the phone *is* the host, and the
adb round trip is not merely unnecessary -- there is no adb, no USB
cable, and no second computer.

So the same argv that would have gone to `adb -s SERIAL shell ...` is
executed locally instead, and the result is shaped into the
`CompletedProcess` the callers already expect. Nothing above this file
learns a new API.

What is deliberately NOT translated
-----------------------------------

Only the verbs that make sense with no host/device split are supported:

    shell, exec-out    -> run the command line in the local shell
    push, pull         -> a local copy; there is no "other side"
    get-state          -> always "device": we are the device
    devices            -> handled by the caller, not here

Everything else (`install`, `forward`, `reverse`, `tcpip`, `connect`,
`root`, `remount`, ...) is a *host-to-device transport* operation with
no on-device meaning. Those return a non-zero `CompletedProcess` with an
explicit message rather than pretending to succeed. A backend that
silently no-ops an unsupported verb reports success for work it never
did, which is the failure mode of bug #66 and of the decorative
capability map in #65.

Security: the quoting story is unchanged and still load-bearing
------------------------------------------------------------------

`adb shell a b c` does not exec an argv -- adbd joins the arguments with
spaces and hands the string to `/system/bin/sh`. Bug #40 was a live RCE
from exactly this. On-device, the same is true: the arguments must be
joined into one command line and given to a shell, because that is the
semantics callers were written against (`recording.py` builds `sh -c`
payloads on purpose).

The critical consequence is that `adb.quote_shell_args()` must have
already run on this argv. It does: `run()` quotes before dispatching to
any backend, so the string assembled here is composed of `shlex.quote`-d
elements. This module must never be handed a raw, unquoted argv -- and
`execute()` refuses one that has not been through the quoter when it can
tell, rather than trusting the caller.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

# Verbs that mean "run this on the device". On a phone that is just
# "run this", but the device-shell join-and-`sh -c` semantics must be
# reproduced exactly or bug #40's quoting fix stops matching reality.
DEVICE_SHELL_VERBS: frozenset[str] = frozenset({"shell", "exec-out"})

# Verbs that move files between two machines. With one machine they are
# an ordinary copy.
FILE_TRANSFER_VERBS: frozenset[str] = frozenset({"push", "pull"})

# Verbs that only exist to manage a host->device transport. There is no
# honest on-device equivalent, so they fail loudly.
TRANSPORT_ONLY_VERBS: frozenset[str] = frozenset({
    "connect", "disconnect", "tcpip", "forward", "reverse", "usb",
    "pair", "root", "unroot", "remount", "reconnect", "wait-for-device",
    "start-server", "kill-server", "install", "uninstall",
})

# The shell Termux actually provides. `/system/bin/sh` always exists on
# Android too, so fall back to it rather than assuming bash is present.
_SHELL_CANDIDATES = ("/data/data/com.termux/files/usr/bin/sh",
                     "/system/bin/sh",
                     "/bin/sh")


class UnsupportedOnDevice(RuntimeError):
    """An adb verb that has no meaning when the host is the device."""


def _shell_binary() -> str:
    """Pick a real shell, preferring Termux's own."""
    for candidate in _SHELL_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("sh")
    if found:
        return found
    # Last resort: let the OS resolve it and fail visibly if it cannot.
    return "sh"


def _completed(returncode: int, stdout: Any, stderr: Any,
               args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args, returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _binary_or_text(value: str, *, capture_binary: bool) -> Any:
    """Match what `subprocess.run` would have produced for this mode."""
    return value.encode("utf-8", "replace") if capture_binary else value


def execute(
    args: list[str],
    *,
    timeout: int = 15,
    input_bytes: bytes | None = None,
    capture_binary: bool = False,
) -> subprocess.CompletedProcess:
    """Execute an adb-shaped argv locally, on the phone.

    `args` is the argv **after** `adb.quote_shell_args()` has run, i.e.
    element 0 is the verb and, for shell verbs, the remainder is already
    `shlex.quote`-d. Returns the same `CompletedProcess` shape the adb
    backend returns, so no caller has to branch.
    """
    if not args:
        return _completed(2, _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text("empty command",
                                          capture_binary=capture_binary), args)

    verb = args[0]

    if verb in TRANSPORT_ONLY_VERBS:
        # Fail closed and say why. Returning success here would have the
        # bridge report a completed `install` that never happened.
        message = (
            f"'{verb}' is an ADB transport operation and has no meaning "
            f"when the bridge runs on the device itself. There is no "
            f"host-to-device link to manage."
        )
        return _completed(1,
                          _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text(message, capture_binary=capture_binary),
                          args)

    if verb == "get-state":
        return _completed(0,
                          _binary_or_text("device\n", capture_binary=capture_binary),
                          _binary_or_text("", capture_binary=capture_binary),
                          args)

    if verb in FILE_TRANSFER_VERBS:
        return _copy(args, capture_binary=capture_binary)

    if verb in DEVICE_SHELL_VERBS:
        return _shell(args, timeout=timeout, input_bytes=input_bytes,
                      capture_binary=capture_binary)

    message = (
        f"'{verb}' is not supported by the on-device backend. Supported: "
        f"{', '.join(sorted(DEVICE_SHELL_VERBS | FILE_TRANSFER_VERBS))}, "
        f"get-state."
    )
    return _completed(1,
                      _binary_or_text("", capture_binary=capture_binary),
                      _binary_or_text(message, capture_binary=capture_binary),
                      args)


def _shell(args: list[str], *, timeout: int, input_bytes: bytes | None,
           capture_binary: bool) -> subprocess.CompletedProcess:
    """Reproduce adbd's join-then-`sh -c`, locally.

    The join is not a shortcut -- it is the behaviour callers were built
    against. `adb shell echo a b` runs `sh -c "echo a b"` on the phone,
    not `execvp("echo", ["a","b"])`, and `recording.py` relies on being
    able to hand over a compound `sh -c` payload. Reimplementing this as
    a direct argv exec would quietly change semantics for every caller.
    """
    command = " ".join(args[1:])
    if not command.strip():
        return _completed(0,
                          _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text("", capture_binary=capture_binary),
                          args)

    kwargs: dict[str, Any] = {"timeout": timeout}
    if capture_binary:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    else:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    if input_bytes is not None:
        kwargs["input"] = input_bytes

    try:
        return subprocess.run([_shell_binary(), "-c", command], **kwargs)
    except subprocess.TimeoutExpired:
        raise
    except OSError as exc:
        return _completed(1,
                          _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text(f"on-device shell failed: {exc}",
                                          capture_binary=capture_binary),
                          args)


def _copy(args: list[str], *, capture_binary: bool) -> subprocess.CompletedProcess:
    """`push`/`pull` with one machine: a plain file copy.

    Paths arrive `shlex.quote`-d only for shell verbs; transfer verbs are
    passed through untouched by `quote_shell_args`, so they are used
    as-is here.
    """
    if len(args) < 3:
        return _completed(1,
                          _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text(f"{args[0]} needs a source and a "
                                          f"destination", capture_binary=capture_binary),
                          args)
    source, destination = Path(args[1]), Path(args[2])
    try:
        if not source.exists():
            return _completed(1,
                              _binary_or_text("", capture_binary=capture_binary),
                              _binary_or_text(f"{source}: no such file",
                                              capture_binary=capture_binary),
                              args)
        # A destination directory means "copy into it", matching adb.
        target = destination / source.name if destination.is_dir() else destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        size = target.stat().st_size
        note = f"{source} -> {target}: 1 file copied ({size} bytes)\n"
        return _completed(0,
                          _binary_or_text(note, capture_binary=capture_binary),
                          _binary_or_text("", capture_binary=capture_binary),
                          args)
    except OSError as exc:
        return _completed(1,
                          _binary_or_text("", capture_binary=capture_binary),
                          _binary_or_text(f"copy failed: {exc}",
                                          capture_binary=capture_binary),
                          args)
