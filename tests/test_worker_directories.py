"""An xdist worker runs in per-user and temporary directories nobody else uses."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _worker_directories as worker_directories


class _Config(SimpleNamespace):
    """The two things the plugin reads from pytest's config."""

    def __init__(self, **attributes):
        """Start with an empty stash, as pytest does."""
        super().__init__(stash=pytest.Stash(), **attributes)


@pytest.fixture(name="base")
def _base(monkeypatch, tmp_path):
    """Start from a known environment: one variable set, two absent."""
    monkeypatch.setenv("HOME", "ambient-home")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("PYTHON_MANAGER_AUTOMATIC_INSTALL", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path.resolve()


def _moved(worker: str) -> tuple[_Config, dict[str, Path]]:
    """Configure one worker and read back where it was moved to."""
    config = _Config(workerinput={"workerid": worker})
    worker_directories.pytest_configure(config)
    return config, {name: Path(os.environ[name]) for name in worker_directories.PRIVATE}


def test_a_worker_is_moved_to_directories_of_its_own(base):
    """Every variable names a fresh, empty, private directory under one root."""
    config, moved = _moved("gw7")
    try:
        assert len(set(moved.values())) == len(worker_directories.PRIVATE)
        (root,) = {path.parent for path in moved.values()}
        assert root.parent == base and root.name.startswith("arena-test-worker-gw7-")
        assert all(path.is_dir() and not any(path.iterdir()) for path in moved.values())
        assert Path.home() == moved["USERPROFILE" if os.name == "nt" else "HOME"]
        assert Path(tempfile.gettempdir()) in {moved["TMPDIR"], moved["TEMP"], moved["TMP"]}
        assert os.environ["PYTHON_MANAGER_AUTOMATIC_INSTALL"] == "false"
    finally:
        worker_directories.pytest_unconfigure(config)
    assert os.environ["HOME"] == "ambient-home"
    assert "XDG_STATE_HOME" not in os.environ
    assert "PYTHON_MANAGER_AUTOMATIC_INSTALL" not in os.environ
    assert not root.exists()


def test_the_home_is_beside_the_temporary_directory_not_inside_it(base):
    """A home inside the temporary directory is what autostart refuses (#381)."""
    config, moved = _moved("gw0")
    try:
        scratch = {moved["TMPDIR"], moved["TEMP"], moved["TMP"]}
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            assert not scratch & {moved[name], *moved[name].parents}, name
    finally:
        worker_directories.pytest_unconfigure(config)


def test_the_directories_are_named_without_a_symlink(base, tmp_path):
    """`private_paths.pinned_directory` refuses a symlink in any component."""
    link, real = tmp_path / "link", tmp_path / "real"
    real.mkdir()
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("this account may not create symlinks")
    tempfile.tempdir = str(link)
    config, moved = _moved("gw0")
    try:
        assert all(path == path.resolve() for path in moved.values())
        assert all((base / "real") in path.parents for path in moved.values())
    finally:
        worker_directories.pytest_unconfigure(config)


def test_an_agent_home_the_run_inherited_is_not_shared_either(base, monkeypatch):
    """`ARENA_AGENT_HOME` outranks the home, so one set outside would be common."""
    monkeypatch.setenv("ARENA_AGENT_HOME", "ambient-agent-home")
    config, moved = _moved("gw0")
    try:
        agent_home = Path(os.environ["ARENA_AGENT_HOME"])
        assert agent_home.is_dir() and agent_home.parent == moved["HOME"].parent
        assert agent_home not in moved.values()
    finally:
        worker_directories.pytest_unconfigure(config)
    assert os.environ["ARENA_AGENT_HOME"] == "ambient-agent-home"


def test_an_agent_home_nobody_set_stays_unset(base, monkeypatch):
    """Tests of the default location must still see no override."""
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    config, _ = _moved("gw0")
    try:
        assert "ARENA_AGENT_HOME" not in os.environ
    finally:
        worker_directories.pytest_unconfigure(config)


def test_two_workers_never_share_a_directory(base):
    """The point of the plugin: what two workers are given is disjoint."""
    seen = []
    for worker in ("gw0", "gw1"):
        config, moved = _moved(worker)
        seen.append(set(moved.values()))
        worker_directories.pytest_unconfigure(config)
    assert seen[0].isdisjoint(seen[1])


def test_the_serial_run_keeps_its_environment(base):
    """One process has nobody to share with, so nothing is moved or created."""
    config = _Config()
    before = dict(os.environ)
    worker_directories.pytest_configure(config)
    worker_directories.pytest_unconfigure(config)
    assert dict(os.environ) == before
    assert Path(tempfile.gettempdir()).resolve() == base
    assert list(base.iterdir()) == []


def test_this_session_obeys_the_rule(request):
    """Under xdist this very test runs in moved directories; serially it does not."""
    home = Path(os.environ.get("USERPROFILE" if os.name == "nt" else "HOME", ""))
    assert home.parent.name.startswith("arena-test-worker-") == hasattr(request.config, "workerinput")
