"""A reader that has a state file open for a moment must not cost its next version (#581)."""
# Windows refuses to replace a file while another handle has it open. The final
# `meta.json` of a detached subagent was published exactly once, so a status poll
# at that moment left the run "spawned" for good while its monitor was gone.
from __future__ import annotations

import json
import os
import threading
import time
import types

import pytest

from arena import private_state


def _held_open(winerror: int) -> PermissionError:
    """Build the refusal Windows gives while another handle has the file open."""
    refusal = PermissionError(13, "the file is open elsewhere")
    refusal.winerror = winerror
    return refusal


@pytest.fixture(name="clock")
def _clock(monkeypatch):
    """Replace the module's clock: a pause moves time forward and is recorded."""
    state = types.SimpleNamespace(now=100.0, pauses=[])

    def pause(seconds):
        state.pauses.append(seconds)
        state.now += seconds

    monkeypatch.setattr(private_state, "time", types.SimpleNamespace(sleep=pause, monotonic=lambda: state.now))
    return state


def _refuse(monkeypatch, refusals):
    """Make publication raise each of `refusals` in turn, then really replace."""
    pending = list(refusals)
    calls = []
    real = private_state._replace

    def replace(*args, **kwargs):
        calls.append(args)
        if pending:
            raise pending.pop(0)
        return real(*args, **kwargs)

    monkeypatch.setattr(private_state, "_replace", replace)
    return calls


@pytest.mark.parametrize("winerror", [5, 32])
def test_a_file_held_open_for_a_moment_is_published_once_it_is_released(tmp_path, monkeypatch, clock, winerror):
    target = tmp_path / "meta.json"
    target.write_text('{"status": "spawned"}\n')
    calls = _refuse(monkeypatch, [_held_open(winerror), _held_open(winerror)])

    private_state.write_private_json(target, {"status": "timeout"})

    assert json.loads(target.read_text()) == {"status": "timeout"}
    assert len(calls) == 3
    assert clock.pauses == [0.005, 0.01]
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_file_held_past_the_limit_raises_the_refusal_and_keeps_the_old_bytes(tmp_path, monkeypatch, clock):
    target = tmp_path / "meta.json"
    target.write_text('{"status": "spawned"}\n')
    before = target.read_bytes()
    calls = _refuse(monkeypatch, [_held_open(5) for _ in range(1000)])

    with pytest.raises(PermissionError) as raised:
        private_state.write_private_json(target, {"status": "timeout"})

    assert raised.value.winerror == 5
    assert target.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
    waited = sum(clock.pauses)
    assert private_state._HELD_OPEN_PATIENCE <= waited <= private_state._HELD_OPEN_PATIENCE + 0.05
    assert max(clock.pauses) == 0.05
    assert len(calls) == len(clock.pauses) + 1


@pytest.mark.parametrize("refusal", [
    PermissionError(13, "the directory is read-only"),
    _held_open(1314),
    FileNotFoundError(2, "the staged file is gone"),
], ids=["no-winerror", "another-winerror", "not-a-permission-error"])
def test_a_refusal_that_is_not_a_held_file_is_raised_at_once(tmp_path, monkeypatch, clock, refusal):
    target = tmp_path / "meta.json"
    calls = _refuse(monkeypatch, [refusal])

    with pytest.raises(type(refusal)) as raised:
        private_state.write_private_json(target, {"status": "timeout"})

    assert raised.value is refusal
    assert len(calls) == 1
    assert clock.pauses == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_file_nobody_holds_is_published_without_a_pause(tmp_path, clock):
    target = tmp_path / "meta.json"
    target.write_text('{"status": "spawned"}\n')

    private_state.write_private_json(target, {"status": "ok"})

    assert json.loads(target.read_text()) == {"status": "ok"}
    assert clock.pauses == []


def test_a_new_file_that_must_not_overwrite_is_never_retried(tmp_path, monkeypatch, clock):
    target = tmp_path / "task.json"
    calls = _refuse(monkeypatch, [])
    private_state.write_private_json(target, {"first": True}, replace=False)

    with pytest.raises(FileExistsError):
        private_state.write_private_json(target, {"second": True}, replace=False)

    assert json.loads(target.read_text()) == {"first": True}
    assert calls == []
    assert clock.pauses == []


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to replace a file that is open")
def test_windows_publishes_over_a_file_a_reader_closes_shortly_after(tmp_path):
    target = tmp_path / "meta.json"
    target.write_text('{"status": "spawned"}\n')
    reader = target.open(encoding="utf-8")
    release = threading.Timer(0.3, reader.close)
    release.start()
    try:
        started = time.monotonic()
        private_state.write_private_json(target, {"status": "timeout"})
        waited = time.monotonic() - started
    finally:
        release.cancel()
        reader.close()
        release.join()

    assert json.loads(target.read_text()) == {"status": "timeout"}
    assert waited >= 0.2
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to replace a file that is open")
def test_windows_gives_up_on_a_file_that_stays_open(tmp_path, monkeypatch):
    monkeypatch.setattr(private_state, "_HELD_OPEN_PATIENCE", 0.2)
    target = tmp_path / "meta.json"
    target.write_text('{"status": "spawned"}\n')
    before = target.read_bytes()

    with target.open(encoding="utf-8"), pytest.raises(PermissionError):
        private_state.write_private_json(target, {"status": "timeout"})

    assert target.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
