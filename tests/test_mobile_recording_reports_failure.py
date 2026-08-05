"""Stop and purge must not claim success when the device never heard them.

Bugs #44 and #45, both the same shape: the adb call was wrapped in
`except Exception: pass` and the function returned a hardcoded
`{"ok": True}` afterwards.

    try:
        run(["shell", "kill", "-INT", str(pid)], ...)
    except Exception:
        pass
    ...
    return {"ok": True, ..., "status": "stopped"}

With adb unreachable the caller was told:

  * `record_stop` -> `ok: True, status: "stopped"` while screenrecord is
    still running on the phone. The lie points the wrong way: an agent
    that believes the camera is off will act as if it is.
  * `record_purge` -> `ok: True` while every MP4 is still on the device.
    For a purge, "ok" is a privacy claim, not a status code.

Neither call raises now -- a stop or purge that partly worked should not
look like a crash -- but the outcome is reported.

Sabotage record (mandatory per AGENTS.md):
  1. restoring `except Exception: pass` + `"ok": True` in stop_async
     -> test_stop_reports_failure_when_adb_is_down fails.
  2. same in purge_recordings
     -> test_purge_reports_failure_when_adb_is_down fails.
  3. ignoring a non-zero returncode (only catching exceptions)
     -> the *_nonzero_exit tests fail.
"""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture()
def recording(monkeypatch, tmp_path):
    """Isolate the module registry and the on-device directory."""
    from arena.mobile import recording as rec

    monkeypatch.setattr(rec, "_RECORD_DIR", str(tmp_path / "sdcard"))
    monkeypatch.setattr(rec, "_REGISTRY", {}, raising=False)
    monkeypatch.setattr(rec, "_ensure_adb", lambda: None)
    return rec


def _dead_adb(*_args, **_kwargs):
    raise RuntimeError("adb transport died")


def _exit_code(code: int, stderr: str = ""):
    def _run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["adb"], returncode=code, stdout="", stderr=stderr)
    return _run


# ---------------------------------------------------------------------------
# stop_async
# ---------------------------------------------------------------------------

def test_stop_reports_failure_when_adb_is_down(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _dead_adb)
    recording._REGISTRY["r1"] = {
        "serial": "s", "pid": 123, "remote_path": "/sdcard/x.mp4",
        "started_at": 0, "status": "recording",
    }

    result = recording.stop_async("r1")

    assert result["ok"] is False, (
        "stop_async claimed success while the phone kept recording"
    )
    assert result["status"] == "stop_failed"
    assert "error" in result and result.get("hint")


def test_stop_reports_failure_on_nonzero_exit(recording, monkeypatch):
    monkeypatch.setattr(recording, "run",
                        _exit_code(1, "kill: no such process"))
    recording._REGISTRY["r2"] = {
        "serial": "s", "pid": 999, "remote_path": "/sdcard/y.mp4",
        "started_at": 0, "status": "recording",
    }

    result = recording.stop_async("r2")

    assert result["ok"] is False
    assert "no such process" in result["error"]


def test_stop_still_succeeds_on_the_happy_path(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _exit_code(0))
    monkeypatch.setattr(recording, "_stat_remote", lambda *a, **k: (0, 4096))
    recording._REGISTRY["r3"] = {
        "serial": "s", "pid": 42, "remote_path": "/sdcard/z.mp4",
        "started_at": 0, "status": "recording",
    }

    result = recording.stop_async("r3")

    assert result["ok"] is True
    assert result["status"] == "stopped"
    assert result["size_bytes"] == 4096
    assert "error" not in result


def test_stop_marks_the_registry_entry_as_failed(recording, monkeypatch):
    """A later `list_recordings` must not show it as cleanly stopped."""
    monkeypatch.setattr(recording, "run", _dead_adb)
    recording._REGISTRY["r4"] = {
        "serial": "s", "pid": 7, "remote_path": "/sdcard/w.mp4",
        "started_at": 0, "status": "recording",
    }

    recording.stop_async("r4")

    assert recording._REGISTRY["r4"]["status"] == "stop_failed"


def test_unknown_recording_id_is_still_a_clean_refusal(recording):
    result = recording.stop_async("nope")
    assert result["ok"] is False
    assert "unknown recording id" in result["error"]


# ---------------------------------------------------------------------------
# purge_recordings
# ---------------------------------------------------------------------------

def test_purge_reports_failure_when_adb_is_down(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _dead_adb)

    result = recording.purge_recordings("s")

    assert result["ok"] is False, (
        "purge claimed the recordings were deleted while adb never ran"
    )
    assert "error" in result and result.get("hint")


def test_purge_reports_failure_on_nonzero_exit(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _exit_code(1, "rm: permission denied"))

    result = recording.purge_recordings("s")

    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_purge_with_age_filter_reports_failure_too(recording, monkeypatch):
    """The `older_than_seconds > 0` branch had its own `except: pass`."""
    monkeypatch.setattr(recording, "run", _dead_adb)

    result = recording.purge_recordings("s", older_than_seconds=60)

    assert result["ok"] is False


def test_purge_still_succeeds_on_the_happy_path(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _exit_code(0))

    result = recording.purge_recordings("s")

    assert result["ok"] is True
    assert "error" not in result
    assert result["cleared_ids"] == []


def test_purge_clears_matching_registry_entries(recording, monkeypatch):
    monkeypatch.setattr(recording, "run", _exit_code(0))
    recording._REGISTRY["mine"] = {"serial": "s", "started_at": 0}
    recording._REGISTRY["other"] = {"serial": "other-device", "started_at": 0}

    result = recording.purge_recordings("s")

    assert result["cleared_ids"] == ["mine"]
    assert "other" in recording._REGISTRY, "purged a different device's entry"


def test_failed_purge_still_reports_what_it_cleared_locally(recording, monkeypatch):
    """Honesty cuts both ways: the local registry WAS cleared, say so."""
    monkeypatch.setattr(recording, "run", _dead_adb)
    recording._REGISTRY["mine"] = {"serial": "s", "started_at": 0}

    result = recording.purge_recordings("s")

    assert result["ok"] is False
    assert result["cleared_ids"] == ["mine"]
    assert "still be on the phone" in result["hint"]


# ---------------------------------------------------------------------------
# Ratchet: no other device-mutating call in this module may swallow errors.
# ---------------------------------------------------------------------------

def test_no_silent_except_pass_around_device_writes():
    """`except Exception: pass` directly around a `run([...])` that mutates
    the device is what produced both bugs. Reads may stay best-effort.
    """
    import pathlib

    # Scanned line by line rather than with a regex: the obvious
    # `try:\n(body)+?except...pass` pattern backtracks catastrophically on
    # this file and hung the suite for minutes before pytest-timeout cut
    # it off. A linear scan is both faster and easier to read.
    lines = (pathlib.Path(__file__).resolve().parents[1]
             / "arena" / "mobile" / "recording.py"
             ).read_text(encoding="utf-8").splitlines()

    mutating = ('"kill"', "rm -f", '"mkdir"', "screenrecord")
    offenders = []
    for index, line in enumerate(lines):
        if line.strip() != "try:":
            continue
        # Collect until the matching `except` at the same indentation.
        indent = len(line) - len(line.lstrip())
        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            current = lines[cursor]
            if current.strip() and (len(current) - len(current.lstrip())) <= indent:
                break
            body.append(current)
            cursor += 1
        if cursor >= len(lines) or not lines[cursor].strip().startswith("except"):
            continue
        handler = lines[cursor + 1] if cursor + 1 < len(lines) else ""
        if handler.strip() != "pass":
            continue
        joined = "\n".join(body)
        if "run([" not in joined or not any(v in joined for v in mutating):
            continue
        # `_ensure_record_dir` swallows on purpose and says why in its
        # docstring: if the mkdir fails, screenrecord itself produces a
        # better error a moment later, so reporting here would be noise.
        # A detector that flags a deliberate, documented decision teaches
        # people to ignore it -- so require the justification to be
        # written down, and accept it when it is.
        preceding = "\n".join(lines[max(0, index - 12):index])
        if "Ignores errors" in preceding or "best-effort" in preceding.lower():
            continue
        offenders.append(f"recording.py:{index + 1}")

    assert not offenders, (
        "these device-mutating calls swallow failures and let the caller "
        f"believe they worked: {offenders}"
    )
