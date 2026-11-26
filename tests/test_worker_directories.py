"""A process that runs tests has per-user and temporary directories nobody else uses."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _worker_directories as worker_directories


class _Config(SimpleNamespace):
    """The three things the plugin reads from pytest's config."""

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


def test_a_run_without_workers_is_moved_too(base, monkeypatch):
    """It has no worker to meet, but it has the account's own files (#608)."""
    monkeypatch.delenv(worker_directories.TMP_PATH_ROOT, raising=False)
    config = _Config()
    before = dict(os.environ)
    worker_directories.pytest_configure(config)
    try:
        moved = {name: Path(os.environ[name]) for name in worker_directories.PRIVATE}
        (root,) = {path.parent for path in moved.values()}
        assert root.parent == base
        assert root.name.startswith("arena-test-worker-serial-")
        assert Path.home() == moved["USERPROFILE" if os.name == "nt" else "HOME"]
        assert Path(tempfile.gettempdir()) in {moved["TMPDIR"], moved["TEMP"], moved["TMP"]}
    finally:
        worker_directories.pytest_unconfigure(config)
    assert dict(os.environ) == before
    assert list(base.iterdir()) == []


@pytest.mark.parametrize("inherited", [None, "somewhere-the-developer-chose"])
def test_a_run_without_workers_keeps_tmp_path_where_it_was(base, monkeypatch, inherited):
    """What a failed test left in `tmp_path` must outlive the moved directories."""
    if inherited is None:
        monkeypatch.delenv(worker_directories.TMP_PATH_ROOT, raising=False)
    else:
        monkeypatch.setenv(worker_directories.TMP_PATH_ROOT, inherited)
    expected = str(base) if inherited is None else inherited
    config = _Config()
    worker_directories.pytest_configure(config)
    try:
        assert os.environ[worker_directories.TMP_PATH_ROOT] == expected
    finally:
        worker_directories.pytest_unconfigure(config)
    assert os.environ.get(worker_directories.TMP_PATH_ROOT) == inherited


def test_a_worker_is_handed_its_tmp_path_and_the_variable_is_left_alone(base, monkeypatch):
    """The controller names a worker's base directory itself."""
    monkeypatch.delenv(worker_directories.TMP_PATH_ROOT, raising=False)
    config, _ = _moved("gw0")
    try:
        assert worker_directories.TMP_PATH_ROOT not in os.environ
    finally:
        worker_directories.pytest_unconfigure(config)


@pytest.mark.parametrize(("platform", "environ", "expected"), [
    ("linux", {}, Path("home", ".cache", "ms-playwright")),
    ("linux", {"XDG_CACHE_HOME": "cache"}, Path("cache", "ms-playwright")),
    ("darwin", {"XDG_CACHE_HOME": "cache"}, Path("home", "Library", "Caches", "ms-playwright")),
    ("win32", {}, Path("home", "AppData", "Local", "ms-playwright")),
    ("win32", {"LOCALAPPDATA": "local"}, Path("local", "ms-playwright")),
])
def test_the_browsers_are_looked_for_where_playwright_puts_them(platform, environ, expected):
    """The three rules of Playwright's own `computeDefaultCacheDirectory`."""
    found = worker_directories.installed_browsers(platform, environ, Path("home"))
    assert found == expected


@pytest.fixture(name="browsers")
def _browsers(monkeypatch, tmp_path_factory):
    """Browsers installed in the account, and no variable naming them."""
    installed = tmp_path_factory.mktemp("ms-playwright")
    monkeypatch.setattr(worker_directories, "installed_browsers", lambda *_: installed)
    monkeypatch.delenv(worker_directories.BROWSERS, raising=False)
    return installed


def _browsers_after_the_move(config: _Config) -> str | None:
    """Configure one run and read back what Playwright will be told."""
    worker_directories.pytest_configure(config)
    try:
        return os.environ.get(worker_directories.BROWSERS)
    finally:
        worker_directories.pytest_unconfigure(config)


def test_a_run_without_workers_still_finds_the_installed_browsers(base, browsers):
    """In a moved home Playwright finds none and every browser test is skipped."""
    assert _browsers_after_the_move(_Config()) == str(browsers)
    assert worker_directories.BROWSERS not in os.environ


def test_browsers_somebody_named_are_left_as_named(base, browsers, monkeypatch):
    """`0` is Playwright's word for "inside the package", not a path to replace."""
    monkeypatch.setenv(worker_directories.BROWSERS, "0")
    assert _browsers_after_the_move(_Config()) == "0"
    assert os.environ[worker_directories.BROWSERS] == "0"


def test_browsers_that_are_not_installed_are_not_named(base, browsers):
    """A path to nothing would only hide where a later install went."""
    browsers.rmdir()
    assert _browsers_after_the_move(_Config()) is None


def test_a_worker_is_not_told_where_the_browsers_are(base, browsers):
    """A parallel run skips the browser tests today; this change leaves that alone."""
    assert _browsers_after_the_move(_Config(workerinput={"workerid": "gw0"})) is None


@pytest.mark.parametrize("dist", ["load", "worksteal"])
def test_the_controller_of_a_parallel_run_keeps_its_environment(base, dist):
    """It runs no test and starts the workers, which move themselves."""
    config = _Config(option=SimpleNamespace(dist=dist))
    before = dict(os.environ)
    worker_directories.pytest_configure(config)
    worker_directories.pytest_unconfigure(config)
    assert dict(os.environ) == before
    assert Path(tempfile.gettempdir()).resolve() == base
    assert list(base.iterdir()) == []


def test_a_run_that_does_not_distribute_is_not_taken_for_a_controller(base):
    """`-n 0` and a run without xdist both say "no"."""
    config = _Config(option=SimpleNamespace(dist="no"))
    worker_directories.pytest_configure(config)
    try:
        assert Path.home().parent.name.startswith("arena-test-worker-serial-")
    finally:
        worker_directories.pytest_unconfigure(config)


def test_this_session_obeys_the_rule(request, tmp_path):
    """This very test runs in moved directories, with or without workers."""
    home = Path(os.environ.get("USERPROFILE" if os.name == "nt" else "HOME", ""))
    label = getattr(request.config, "workerinput", {}).get("workerid", "serial")
    assert home.parent.name.startswith(f"arena-test-worker-{label}-")
    assert home.parent not in tmp_path.parents
