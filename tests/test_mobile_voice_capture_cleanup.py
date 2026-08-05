"""Microphone captures must not be left on the phone, or lied about.

Two bugs in `arena/mobile/audio_capture.py`, both about the same file:
the `.m4a` that `voice_record` records through the device microphone.

#46 -- the cleanup claimed success it did not have:

        try:
            run(["shell", "rm", "-f", output, marker], ...)
            result["cleaned_up"] = True
        except Exception:
            pass

    `run()` returns a CompletedProcess; it does not raise on a non-zero
    exit. So an `rm` answering "Permission denied" still set
    `cleaned_up: True`, and the caller was told a microphone recording had
    been deleted from the device while it was still sitting in
    /sdcard/DCIM. For voice capture that is a privacy claim, not a status
    field.

#47 -- no failure path cleaned up at all. Timeout, recorder-reported
    error and empty-pull all returned early, leaving captured audio on the
    device forever. A capture that FAILED is precisely the one nobody
    comes back for, so it is where an orphaned recording matters most.

    The failed-`pull` path is the deliberate exception: the bytes exist
    only on the phone and the transfer is what broke, so deleting them
    would destroy the recording. It keeps the file and says so explicitly
    rather than being quietly inconsistent.

Sabotage record (mandatory per AGENTS.md):
  1. `_cleanup_device` -> always `{"cleaned_up": True}`
     -> test_cleanup_failure_is_reported fails.
  2. dropping the cleanup call from the timeout path
     -> test_timeout_still_removes_the_recording fails.
  3. dropping it from the recorder-error path
     -> test_recorder_error_still_removes_the_recording fails.
  4. adding cleanup to the failed-pull path
     -> test_failed_pull_keeps_the_recording_on_purpose fails.
"""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture()
def capture(monkeypatch, tmp_path):
    """A voice_record that never touches a real device."""
    from arena.mobile import audio_capture as ac

    monkeypatch.setattr(ac, "_ensure_adb", lambda: None)
    monkeypatch.setattr(ac, "ensure_installed", lambda s, **k: {"ok": True})
    monkeypatch.setattr(ac, "ensure_permissions", lambda s: {"ok": True})
    monkeypatch.setattr(ac, "voice_capture_dir", lambda: tmp_path)
    # Keep the poll loop short; the timeout path is exercised on purpose.
    monkeypatch.setattr(ac, "_DONE_TIMEOUT_BUFFER_S", 0.2)
    monkeypatch.setattr(ac, "_POLL_INTERVAL_S", 0.05)
    return ac


class _Adb:
    """Records every adb invocation and lets tests fail chosen ones."""

    def __init__(self, *, rm_exit: int = 0, pull_exit: int = 0,
                 pull_bytes: bytes = b"AUDIO" * 40):
        self.calls: list[list[str]] = []
        self.rm_exit = rm_exit
        self.pull_exit = pull_exit
        self.pull_bytes = pull_bytes

    def __call__(self, args, **_kwargs):
        import pathlib

        self.calls.append(list(args))
        if args[:2] == ["shell", "rm"] and self.rm_exit:
            return subprocess.CompletedProcess(
                args, self.rm_exit, "", "rm: Permission denied")
        if args and args[0] == "pull":
            if self.pull_exit:
                return subprocess.CompletedProcess(
                    args, self.pull_exit, "", "adb: pull failed")
            pathlib.Path(args[2]).write_bytes(self.pull_bytes)
        return subprocess.CompletedProcess(args, 0, "", "")

    @property
    def recording_deletions(self) -> int:
        """`rm -f <output> <marker>` -- the cleanup, not the stale-marker rm."""
        return sum(1 for c in self.calls
                   if c[:2] == ["shell", "rm"] and len(c) > 4)


# ---------------------------------------------------------------------------
# #46: don't claim a cleanup that failed.
# ---------------------------------------------------------------------------

def test_cleanup_failure_is_reported(capture, monkeypatch):
    adb = _Adb(rm_exit=1)
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is True, "the capture itself succeeded"
    assert result["cleaned_up"] is False, (
        "rm exited non-zero but the recording was reported as deleted"
    )
    assert "Permission denied" in result["cleanup_error"]
    assert result.get("cleanup_hint")


def test_successful_cleanup_still_reports_true(capture, monkeypatch):
    adb = _Adb()
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is True
    assert result["cleaned_up"] is True
    assert "cleanup_error" not in result
    assert adb.recording_deletions == 1


def test_cleanup_exception_is_reported(capture, monkeypatch):
    def exploding(args, **_kwargs):
        if args[:2] == ["shell", "rm"] and len(args) > 4:
            raise RuntimeError("adb transport died")
        return _Adb()(args)

    monkeypatch.setattr(capture, "run", exploding)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["cleaned_up"] is False
    assert "adb transport died" in result["cleanup_error"]


def test_keep_on_device_is_honoured(capture, monkeypatch):
    """Explicitly asking to keep the file must not trigger a deletion."""
    adb = _Adb()
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500,
                                  keep_on_device=True)

    assert result["ok"] is True
    assert adb.recording_deletions == 0
    assert "cleaned_up" not in result


# ---------------------------------------------------------------------------
# #47: failure paths must not orphan captured audio.
# ---------------------------------------------------------------------------

def test_timeout_still_removes_the_recording(capture, monkeypatch):
    adb = _Adb()
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: None)

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is False
    assert adb.recording_deletions == 1, (
        "a capture that timed out left microphone audio on the device"
    )
    assert result["cleaned_up"] is True


def test_recorder_error_still_removes_the_recording(capture, monkeypatch):
    adb = _Adb()
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "error:mic-busy")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is False
    assert "mic-busy" in result["error"]
    assert adb.recording_deletions == 1


def test_empty_recording_still_removes_it(capture, monkeypatch):
    adb = _Adb(pull_bytes=b"")
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is False
    assert adb.recording_deletions == 1


def test_failed_pull_keeps_the_recording_on_purpose(capture, monkeypatch):
    """The one path where keeping the file is correct -- and it says so.

    The audio exists only on the phone and the transfer is what failed;
    deleting it here would destroy the capture the caller asked for.
    """
    adb = _Adb(pull_exit=1)
    monkeypatch.setattr(capture, "run", adb)
    monkeypatch.setattr(capture, "_read_done", lambda s, m: "ok")

    result = capture.voice_record("serial", duration_ms=500)

    assert result["ok"] is False
    assert adb.recording_deletions == 0, (
        "the pull failed, so the only copy is on the phone -- deleting it "
        "would lose the recording"
    )
    assert result["cleaned_up"] is False
    assert "still on the device" in result["cleanup_hint"]


def test_every_failure_path_states_a_cleanup_verdict(capture, monkeypatch):
    """No silent middle ground: the caller always learns where the audio is.

    This is the property that actually matters. Whether a given path
    deletes or keeps is a judgement call; leaving the caller unable to
    tell is not.
    """
    scenarios = {
        "timeout": (_Adb(), lambda s, m: None),
        "recorder_error": (_Adb(), lambda s, m: "error:mic-busy"),
        "empty": (_Adb(pull_bytes=b""), lambda s, m: "ok"),
        "pull_failed": (_Adb(pull_exit=1), lambda s, m: "ok"),
        "rm_denied": (_Adb(rm_exit=1), lambda s, m: "ok"),
    }
    for name, (adb, done) in scenarios.items():
        monkeypatch.setattr(capture, "run", adb)
        monkeypatch.setattr(capture, "_read_done", done)

        result = capture.voice_record("serial", duration_ms=500)

        assert "cleaned_up" in result, (
            f"{name}: caller cannot tell whether the microphone recording "
            f"is still on the phone; got {sorted(result)}"
        )
        if result["cleaned_up"] is False:
            assert result.get("cleanup_error") or result.get("cleanup_hint"), (
                f"{name}: reported an uncleaned recording without saying "
                "where it is or why"
            )
