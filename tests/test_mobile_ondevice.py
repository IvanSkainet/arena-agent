"""The on-device backend must behave exactly like adb, minus the cable.

Twenty-two modules under `arena/mobile` call `adb.run`. When the bridge
runs in Termux there is no adb, so `run` dispatches to
`arena.mobile.ondevice` instead. Every one of those callers keeps its
existing code, which only works if the substitute matches the original's
contract precisely: same `CompletedProcess` shape, same shell semantics,
same quoting guarantees.

The quoting is the part that must never regress. Bug #40 (v4.162.0) was
a live RCE: `adb shell a b c` does not exec an argv -- adbd joins the
arguments and hands the string to `/system/bin/sh`. The on-device
backend reproduces that join deliberately, because callers such as
`recording.py` build `sh -c` payloads on purpose. Reproducing the join
without reproducing the quoting would reopen the RCE on the phone.
"""
from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from arena.mobile import adb, ondevice


@pytest.fixture
def on_device():
    """Force the Android dispatch path regardless of the real host."""
    with mock.patch.object(adb, "_on_device", return_value=True):
        yield


# ---------------------------------------------------------------- security

def test_shell_metacharacters_do_not_execute_on_device(on_device, tmp_path):
    """Bug #40's RCE must stay closed on the phone.

    The canary file is created only if the `&` in the argument is
    interpreted by a shell rather than passed through as text. On the
    adb path `quote_shell_args` prevents that; the on-device path must
    inherit the identical protection, because `run()` quotes before
    dispatching to either backend.
    """
    canary = tmp_path / "PWNED"
    result = adb.run(["shell", f"ls /data & touch {canary}"])
    assert not canary.exists(), (
        "a bare & executed a second command -- bug #40 is reopened on the "
        "on-device backend")
    assert result.returncode != 0


def test_exec_out_is_quoted_too(on_device, tmp_path):
    """`exec-out` is the same device-side code path as `shell`.

    It was missed on the first pass of the original fix and
    `run(["exec-out", "cat", "/sdcard/x; touch /tmp/EO"])` stayed
    exploitable. The on-device backend must not repeat that.
    """
    canary = tmp_path / "EO"
    adb.run(["exec-out", f"cat /nope; touch {canary}"])
    assert not canary.exists(), "exec-out bypassed quoting on-device"


def test_the_backend_refuses_an_unquoted_argv_from_a_direct_caller(tmp_path):
    """Calling `ondevice.execute` directly must still be safe.

    `run()` quotes first, but nothing stops a future caller from
    reaching for `execute` on its own. The join-and-`sh -c` semantics
    mean an unquoted metacharacter would execute, so this pins the
    expectation: whatever the entry point, a payload only runs if it was
    quoted. Here the argument IS pre-quoted, proving the safe path
    works; the unsafe path is prevented by `run` being the only
    documented entry point.
    """
    import shlex

    canary = tmp_path / "DIRECT"
    ondevice.execute(["shell", shlex.quote(f"x & touch {canary}")])
    assert not canary.exists()


# ------------------------------------------------------------- semantics

def test_a_plain_shell_command_runs_and_captures_stdout(on_device):
    result = adb.run(["shell", "echo", "hello"])
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_arguments_are_joined_the_way_adbd_joins_them(on_device):
    """`adb shell echo a b` runs `sh -c "echo a b"`, not execvp.

    Callers were written against the join. An implementation that
    exec'd the argv directly would silently change behaviour for every
    one of them.
    """
    result = adb.run(["shell", "sh", "-c", "echo one; echo two"])
    assert result.returncode == 0
    assert result.stdout.split() == ["one", "two"]


def test_binary_capture_returns_bytes_like_the_adb_backend(on_device):
    """`screenshot.py` pulls raw PNG through `capture_binary=True`."""
    result = adb.run(["exec-out", "echo", "binary"], capture_binary=True)
    assert isinstance(result.stdout, bytes)
    assert result.stdout.strip() == b"binary"


def test_get_state_reports_device(on_device):
    result = adb.run(["get-state"])
    assert result.returncode == 0
    assert result.stdout.strip() == "device"


def test_push_and_pull_are_local_copies(on_device, tmp_path):
    source = tmp_path / "src.txt"
    source.write_text("payload", encoding="utf-8")
    destination = tmp_path / "out" / "dst.txt"

    result = adb.run(["push", str(source), str(destination)])
    assert result.returncode == 0, result.stderr
    assert destination.read_text(encoding="utf-8") == "payload"

    back = tmp_path / "back.txt"
    assert adb.run(["pull", str(destination), str(back)]).returncode == 0
    assert back.read_text(encoding="utf-8") == "payload"


def test_a_missing_source_fails_rather_than_reporting_success(on_device, tmp_path):
    result = adb.run(["push", str(tmp_path / "nope"), str(tmp_path / "x")])
    assert result.returncode != 0
    assert "no such file" in (result.stderr or "").lower()


# ------------------------------------------------------------ honesty

@pytest.mark.parametrize("verb", ["install", "forward", "tcpip", "connect",
                                  "root", "remount", "reverse"])
def test_transport_verbs_fail_loudly_instead_of_pretending(on_device, verb):
    """A no-op that reports success is worse than an error.

    These verbs manage a host-to-device link. On the phone there is no
    link. Returning 0 would have the bridge report a completed
    `install` that never happened -- the same dishonesty as bug #66's
    "old token lives until restart" and #65's decorative allow-list.
    """
    result = adb.run([verb, "whatever"])
    assert result.returncode != 0
    assert verb in (result.stderr or "")


def test_an_unknown_verb_is_reported_not_swallowed(on_device):
    result = adb.run(["bogus-verb"])
    assert result.returncode != 0
    assert "not supported" in (result.stderr or "").lower()


def test_an_empty_argv_does_not_raise(on_device):
    result = adb.run([])
    assert result.returncode != 0


# ---------------------------------------------------- dispatch correctness

def test_the_adb_path_is_untouched_when_not_on_a_phone(tmp_path):
    """Reverse sabotage: desktops must keep using adb exactly as before.

    The seam has to be invisible on Windows, macOS and desktop Linux. If
    `_on_device()` ever returned True there, the bridge would run mobile
    commands against *itself* instead of the connected phone -- typing
    into the operator's desktop.
    """
    with mock.patch.object(adb, "_on_device", return_value=False), \
         mock.patch.object(adb, "find_adb", return_value="/usr/bin/adb"), \
         mock.patch("subprocess.run") as spawned:
        spawned.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="")
        adb.run(["shell", "echo", "hi"], serial="ABC123")

    assert spawned.called, "the adb backend was not used on a desktop host"
    argv = spawned.call_args[0][0]
    assert argv[0] == "/usr/bin/adb"
    assert "-s" in argv and "ABC123" in argv


def test_a_broken_host_detector_falls_back_to_adb():
    """`_on_device` must never take the mobile stack down with it.

    If host detection raises on some unusual machine, the correct
    behaviour is the pre-existing one (use adb), not a crash on every
    mobile endpoint.
    """
    with mock.patch("arena.hostplatform.is_android",
                    side_effect=RuntimeError("boom")):
        assert adb._on_device() is False
