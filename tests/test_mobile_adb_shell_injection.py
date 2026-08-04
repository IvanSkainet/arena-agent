"""adb shell must not be a remote code execution primitive (bug #40).

Why this file exists
--------------------
`adb shell a b c` does NOT behave like `subprocess.run(["a","b","c"])`.
adbd joins the argument vector with spaces and feeds the resulting STRING
to `/system/bin/sh` on the device. Passing a Python list therefore buys
exactly zero protection on the phone side.

Before v4.162.0 that was a live, reproduced RCE:

  * `restricted_shell(serial, "ls /data & touch /tmp/PWNED")` returned
    ok=True and created the file -- the metacharacter blocklist covered
    `;`, `&&`, `||`, `|`, backticks and `$(` but NOT a bare `&`.
  * `input.type_text(serial, "hi&touch$IFS/tmp/T3")` executed `touch`
    too -- its `%s` space-escaping was bypassed with `$IFS`.

Both were verified against an adbd stand-in that reproduces the
join-and-`sh -c` behaviour, which is exactly what this file installs.

Sabotage record (mandatory per AGENTS.md)
-----------------------------------------
Each guard below was proven to FAIL against the pre-fix code:
  1. reverting `quote_shell_args` to `return list(args)`
     -> test_type_text_cannot_execute_a_command fails (file created).
  2. restoring the old `forbidden_chars` list
     -> test_restricted_shell_rejects_bare_ampersand fails (ok=True).
  3. dropping only `"*"`/`"~"` from the blocklist
     -> test_restricted_shell_rejects_shell_expansions fails.
"""
from __future__ import annotations

import stat
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the adbd stand-in is a /bin/sh script; the behaviour under test "
           "is device-side and platform-independent, so covering it on "
           "POSIX CI runners is sufficient.",
)

# An adbd stand-in. It reproduces the ONE behaviour that matters: strip
# `-s <serial>`, and for `shell` join the remaining argv with spaces and
# run it through a real shell. If our quoting is correct, the payload
# arrives as inert text; if not, the shell executes it.
_FAKE_ADB = """#!/bin/sh
while [ "$1" = "-s" ]; do shift 2; done
if [ "$1" = "shell" ]; then shift; exec /bin/sh -c "$*"; fi
exit 0
"""


@pytest.fixture()
def fake_adb(tmp_path, monkeypatch):
    """Point arena.mobile.adb at the stand-in above."""
    path = tmp_path / "adb"
    path.write_text(_FAKE_ADB)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    from arena.mobile import adb as adb_mod

    monkeypatch.setattr(adb_mod, "find_adb", lambda: str(path))
    # shell.py and input.py import find_adb by name at module load.
    for mod_name in ("arena.mobile.shell", "arena.mobile.input"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "find_adb"):
            monkeypatch.setattr(mod, "find_adb", lambda: str(path))
    return str(path)


# ---------------------------------------------------------------------------
# The quoting primitive itself.
# ---------------------------------------------------------------------------

def test_quote_shell_args_neutralises_metacharacters():
    from arena.mobile.adb import quote_shell_args

    out = quote_shell_args(["shell", "ls", "/data & touch /tmp/x"])
    assert out[0] == "shell"
    # The dangerous element must no longer be a bare word: whatever the
    # quoting style, re-parsing the joined string must yield the original
    # element as ONE token rather than an operator plus a command.
    import shlex
    assert shlex.split(" ".join(out[1:])) == ["ls", "/data & touch /tmp/x"]


def test_quote_shell_args_leaves_non_shell_invocations_alone():
    """push/pull/install never reach a device shell; quoting them would
    change their semantics for no security gain."""
    from arena.mobile.adb import quote_shell_args

    args = ["push", "/host/my file.txt", "/sdcard/my file.txt"]
    assert quote_shell_args(args) == args
    assert quote_shell_args(["install", "-r", "/tmp/a b.apk"]) == ["install", "-r", "/tmp/a b.apk"]


# ---------------------------------------------------------------------------
# End-to-end: the payload must not execute.
# ---------------------------------------------------------------------------

def test_type_text_cannot_execute_a_command(fake_adb, tmp_path):
    """The original `$IFS` bypass of the %s space-escaping."""
    from arena.mobile.input import type_text

    marker = tmp_path / "pwned_type"
    type_text("emulator-5554", f"hi&touch$IFS{marker}")
    assert not marker.exists(), (
        "type_text executed a shell command on the device: the argv is "
        "joined by adbd and interpreted by /system/bin/sh."
    )


def test_restricted_shell_cannot_execute_a_second_command(fake_adb, tmp_path):
    from arena.mobile.shell import restricted_shell

    marker = tmp_path / "pwned_shell"
    result = restricted_shell("emulator-5554", f"ls /data & touch {marker}")
    assert result["ok"] is False
    assert not marker.exists()


# ---------------------------------------------------------------------------
# The blocklist, as a fail-closed second layer.
# ---------------------------------------------------------------------------

def test_restricted_shell_rejects_bare_ampersand():
    """`&` alone backgrounds a job and starts a new command -- it is every
    bit as dangerous as `&&`, which WAS blocked."""
    from arena.mobile.shell import restricted_shell

    result = restricted_shell("s", "ls /data & touch /tmp/x")
    assert result["ok"] is False
    assert "&" in result["error"]


@pytest.mark.parametrize("payload", [
    "ls /tm*",          # glob expansion happens on the device
    "ls /sdcard/?",     # single-char glob
    "ls ~",             # tilde expansion reaches $HOME on the device
    "cat /proc/$$/cmdline",
    "ls ${HOME}",
    "ls $(pwd)",
    "ls `pwd`",
    "getprop; rm -rf /sdcard",
    "uptime | sh",
    "cat /etc/hosts > /sdcard/leak",
])
def test_restricted_shell_rejects_shell_expansions(payload):
    from arena.mobile.shell import restricted_shell

    result = restricted_shell("s", payload)
    assert result["ok"] is False, f"{payload!r} was accepted"
    assert "not allowed" in result["error"] or "allowlist" in result["error"]


# ---------------------------------------------------------------------------
# A detector with false positives is worse than no detector: the real
# diagnostic commands this endpoint exists for must all still pass.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "getprop ro.product.model",
    "pm list packages",
    "dumpsys battery",
    "dumpsys window displays",
    "settings get system screen_brightness",
    "ls /sdcard/Download",
    "ip -4 addr show wlan0",
    "logcat -d -t 50",
    "cat /proc/meminfo",
    "df -h",
    "wm size",
    "ps -A",
    "top -n 1",
    "printenv PATH",
    "date",
])
def test_legitimate_diagnostics_are_not_blocked(command):
    from arena.mobile.shell import restricted_shell

    result = restricted_shell("s", command)
    error = str(result.get("error") or "")
    assert "not allowed" not in error and "allowlist" not in error, (
        f"validator rejected a legitimate diagnostic command: {command!r} -> {error}"
    )


def test_every_shell_call_site_goes_through_the_quoting_helper():
    """Ratchet: the fix lives in adb.run so no caller can forget it.

    If someone adds a module that spawns adb directly with subprocess
    instead of arena.mobile.adb.run, this catches it.
    """
    import pathlib

    mobile = pathlib.Path(__file__).resolve().parents[1] / "arena" / "mobile"
    offenders = []
    for py in mobile.glob("*.py"):
        if py.name == "adb.py":  # the one module allowed to spawn adb
            continue
        text = py.read_text(encoding="utf-8")
        lines = text.splitlines()
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "subprocess.run" not in stripped and "subprocess.Popen" not in stripped:
                continue
            # Only adb invocations are in scope. Spawning OTHER host tools
            # (apk_install runs `apksigner`, a local binary with a fixed
            # argv and no device shell behind it) is legitimate and must
            # not trip this ratchet -- a detector that cries wolf gets
            # ignored, which is worse than no detector at all.
            window = "\n".join(lines[lineno - 1:lineno + 6]).lower()
            if "adb" in window:
                offenders.append(f"{py.name}:{lineno}: {stripped}")
    assert not offenders, (
        "these call sites spawn adb outside arena.mobile.adb.run and "
        "therefore bypass device-shell quoting:\n" + "\n".join(offenders)
    )
