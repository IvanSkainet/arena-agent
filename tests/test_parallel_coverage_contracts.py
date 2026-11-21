"""T74: cover timing/ambient branches explicitly, not by scheduler accident."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena import file_lock
from arena.inventory import probe_environment


@pytest.mark.parametrize("expires", [False, True])
def test_journal_contention_is_covered_without_real_sleep(monkeypatch, expires):
    attempts = []
    sleeps = []
    ticks = iter([0.0, 1.0 if expires else 0.1])

    @contextmanager
    def directory(path):
        yield None

    @contextmanager
    def lease(path, descriptor):
        attempts.append(path)
        yield len(attempts) > 1

    monkeypatch.setattr(file_lock, "pinned_directory", directory)
    monkeypatch.setattr(file_lock, "lease_in_directory", lease)
    monkeypatch.setattr(file_lock, "time", SimpleNamespace(
        monotonic=lambda: next(ticks), sleep=sleeps.append))
    if expires:
        journal = Path("private/journal")
        with pytest.raises(TimeoutError, match="private journal is busy"):
            with file_lock.journal_lock(journal, timeout=1):
                pass  # Entering without the timeout makes pytest.raises fail.
        assert len(attempts) == 1
        assert sleeps == []
    else:
        with file_lock.journal_lock(Path("private/journal"), timeout=1) as descriptor:
            assert descriptor is None
        assert len(attempts) == 2
        assert sleeps == [.01]


@pytest.mark.parametrize("display_environment", [{}, {"DISPLAY": ":fixture", "XDG_SESSION_TYPE": "wayland"}])
def test_display_probe_does_not_depend_on_worker_ambient_environment(monkeypatch, display_environment):
    monkeypatch.setattr(probe_environment, "platform", SimpleNamespace(system=lambda: "Linux"))
    monkeypatch.setattr(probe_environment, "os", SimpleNamespace(environ=display_environment))
    monkeypatch.setattr(probe_environment, "_which", lambda name: None)
    assert probe_environment.get_displays() == display_environment
