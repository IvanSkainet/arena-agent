"""Screen-mirror stream params reach an adb command line -- validate them.

Bug #48. `GET /v1/mobile/{serial}/mirror/ws?size=...` passed the query
string straight into

    adb -s <serial> exec-out screenrecord --size <size> ...

with no validation whatsoever. `exec-out` is the device shell: adbd joins
the argv with spaces and hands the string to /system/bin/sh on the phone.
Reproduced end to end against an adbd stand-in:

    ?size=720x1600; touch /tmp/MIRROR_PWNED2 #
    -> the file was created.

Two things had to go wrong at once for this to survive v4.162.0:

  * The central quoting fix lives inside `arena.mobile.adb.run`, and
    mirror does not use it -- it spawns adb itself, because `run()` is a
    blocking capture-everything helper and mirror needs a live pipe.
  * The ratchet written to catch exactly that ("no module may spawn adb
    outside adb.run") only looked for `subprocess.run` and
    `subprocess.Popen`. Mirror uses `asyncio.create_subprocess_exec`, so
    the ratchet never saw it. A detector is only as good as its list of
    spawn verbs; that list is now eleven entries long.

Sabotage record (mandatory per AGENTS.md):
  1. `validate_stream_params` -> `return None`
     -> test_shell_metacharacters_in_size_are_refused fails.
  2. removing the guard from `_screenrecord_cmd`
     -> test_command_builder_refuses_bad_size_even_if_a_caller_forgets fails.
  3. dropping `create_subprocess_exec` from the ratchet's verb list
     -> test_the_ratchet_knows_about_async_spawns fails.
"""
from __future__ import annotations

import pytest

from arena.mobile import mirror

# ---------------------------------------------------------------------------
# The injection itself.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "720x1600; touch /tmp/pwned",
    "720x1600; touch /tmp/pwned #",
    "720x1600 && id",
    "720x1600 | sh",
    "720x1600 & id",
    "$(id)",
    "`id`",
    "720x1600\nid",
    "../../etc/passwd",
    "-rf",                 # would be read as another flag
    "--bit-rate=1",        # smuggling a second option
    "",
    "x",
    "0x0",
    "720X1600",            # capital X is not the documented format
    "720 x 1600",
])
def test_shell_metacharacters_in_size_are_refused(payload):
    assert mirror.validate_stream_params(payload, 4_000_000) is not None, (
        f"size={payload!r} was accepted and would reach an adb argv"
    )


def test_command_builder_refuses_bad_size_even_if_a_caller_forgets():
    """Defence in depth: the builder itself must not emit a poisoned argv.

    Every current caller validates first. This asserts the builder does
    not *rely* on that, because the next caller is the one that forgets.
    """
    with pytest.raises(ValueError):
        mirror._screenrecord_cmd("emulator-5554",
                                 "720x1600; touch /tmp/pwned #",
                                 4_000_000)


def test_bit_rate_is_bounded():
    assert mirror.validate_stream_params("720x1600", 0) is not None
    assert mirror.validate_stream_params("720x1600", -1) is not None
    assert mirror.validate_stream_params("720x1600", 99) is not None
    assert mirror.validate_stream_params("720x1600", 10 ** 12) is not None
    assert mirror.validate_stream_params("720x1600", "4000000") is not None


# ---------------------------------------------------------------------------
# A validator that rejects real input is a validator people delete.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size", [
    "720x1600",    # the default
    "1080x2400",
    "1440x3200",
    "480x800",
    "360x640",
    "2160x3840",
])
def test_real_resolutions_are_accepted(size):
    assert mirror.validate_stream_params(size, 4_000_000) is None, (
        f"{size} is an ordinary phone resolution and must stream"
    )


def test_the_default_params_pass_their_own_validator():
    """Trivially true until someone edits one of the two and not the other."""
    assert mirror.validate_stream_params(
        mirror.DEFAULT_SIZE, mirror.DEFAULT_BIT_RATE) is None


def test_valid_params_produce_the_expected_argv():
    cmd = mirror._screenrecord_cmd("emulator-5554", "1080x2400", 6_000_000)
    assert cmd[1:5] == ["-s", "emulator-5554", "exec-out", "screenrecord"]
    assert "--size" in cmd and cmd[cmd.index("--size") + 1] == "1080x2400"
    assert cmd[cmd.index("--bit-rate") + 1] == "6000000"
    assert cmd[-1] == "-"


# ---------------------------------------------------------------------------
# The ratchet's blind spot, pinned so it cannot come back.
# ---------------------------------------------------------------------------

def test_the_ratchet_knows_about_async_spawns():
    """The reason bug #48 survived: the verb list was too short.

    `subprocess.run` is not the only way to start a process, and the one
    module that bypassed the central quoting used a different one.
    """
    from tests.test_mobile_adb_shell_injection import _SPAWN_VERBS

    for verb in ("subprocess.run", "subprocess.Popen",
                 "create_subprocess_exec", "create_subprocess_shell",
                 "os.system", "os.popen"):
        assert verb in _SPAWN_VERBS, (
            f"{verb} can spawn adb but the ratchet does not look for it"
        )


def test_mirror_is_the_only_exempted_spawner():
    """Mirror is allowed to spawn adb directly; that must stay rare.

    It needs a live pipe, which `adb.run` cannot express. The exemption is
    by name in the ratchet so a second module cannot inherit it quietly --
    and mirror pays for it with the validation this file tests.
    """
    import pathlib

    ratchet = (pathlib.Path(__file__).resolve().parent
               / "test_mobile_adb_shell_injection.py").read_text(encoding="utf-8")
    exempted = [name for name in ("mirror.py", "adb.py")
                if f'py.name == "{name}"' in ratchet]
    assert exempted == ["adb.py", "mirror.py"] or set(exempted) == {"adb.py", "mirror.py"}, (
        f"unexpected set of modules exempted from the spawn ratchet: {exempted}"
    )
