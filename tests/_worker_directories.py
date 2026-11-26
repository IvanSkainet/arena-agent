"""Give every process that runs tests per-user and temporary directories of its own."""

# A test that does not name a home uses the account's: about a dozen product
# modules bind `agent_home()` at import, and `make_app()` opens the memory
# database under it. A test that does not name a scratch directory uses the
# system one. One process can live with that. Several cannot -- they are
# separate processes sharing one `~/arena-bridge` and one temporary directory,
# and the hosted runners showed what that costs the first time the suite ran
# there in parallel:
#
# * macOS: two workers created `logs/ws_notify.queue` at the same instant and one
#   got ENOENT, so the workers disagreed on the collected tests;
# * Windows: two workers initialised `memory/facts.db` together and one got
#   `sqlite3.OperationalError: trigger memory_facts_ai already exists`;
# * macOS: a test that expects exactly one `fuzz-root-*` workspace in the
#   temporary directory found the one another worker's test had just made.
#
# Fixing those files one at a time would leave the next shared file to be found
# the same way. So a worker is moved to its own directories before it imports a
# single test module, which is before any of those constants is bound.
#
# A run without workers is moved the same way (#608). It has no other worker
# to meet, but it has the account: left where it was, it appended test
# commands to the real `~/arena-bridge/audit.jsonl`, test traffic to
# `requests.jsonl`, and replaced `~/.arena/last_urls.json` with addresses of
# test servers. Only the controller of a parallel run stays put: it runs no
# test, and its workers move themselves.
#
# The variables are exactly the ones `arena/governance/benchmark_runner.py`
# makes private for a measured run, so the two kinds of run agree. As there, the
# home and the temporary directory are siblings: a home *inside* the temporary
# directory is what the autostart repair refuses to install from (#381).
#
# One thing in the old home is still wanted: the browsers Playwright
# installed. It looks for them under the per-user cache, and in a moved home
# finds none, so every browser test would be skipped and the run would still
# be green. A run without workers is therefore told where they were. A worker
# is told nothing, as before: a parallel run skips those tests today and this
# file does not change that.
#
# `tmp_path` is not moved. The controller hands each worker its base directory
# explicitly, and pytest already names it per worker. A run without workers
# works its base out from the temporary directory on first use, so that
# directory is recorded before the move: what a failed test left in
# `tmp_path` is still there to look at afterwards.

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

#: Where a program looks for "my files" and "scratch space" when nothing more
#: specific is set.
PRIVATE = ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
           "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")

OVERRIDE = "ARENA_AGENT_HOME"

#: pytest's own variable for where `tmp_path` directories are made.
TMP_PATH_ROOT = "PYTEST_DEBUG_TEMPROOT"

#: Playwright's variable for where its browsers are installed.
BROWSERS = "PLAYWRIGHT_BROWSERS_PATH"

_MOVED = pytest.StashKey[tuple]()


def private_directories(root: Path) -> dict[str, str]:
    """Create one private directory per variable under `root`."""
    values = {}
    for name in PRIVATE:
        path = root / name.lower()
        path.mkdir(mode=0o700)
        values[name] = str(path)
    # The Windows Python install manager answers `python3` and `pip`; with an
    # empty per-user directory it sees no runtime and downloads one (#376).
    values["PYTHON_MANAGER_AUTOMATIC_INSTALL"] = "false"
    # `agent_home()` prefers this variable to the home. Where the run
    # inherited one, every worker would still meet in it; where nobody set
    # it, it stays unset, because tests of the default location rely on that.
    if OVERRIDE in os.environ:
        path = root / "arena_agent_home"
        path.mkdir(mode=0o700)
        values[OVERRIDE] = str(path)
    return values


def installed_browsers(platform: str, environ: Mapping[str, str], home: Path) -> Path:
    """Where Playwright keeps its browsers when nothing names the place."""
    # Its own rule: `computeDefaultCacheDirectory` in the driver it ships.
    if platform == "darwin":
        cache = home / "Library" / "Caches"
    elif platform == "win32":
        cache = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        cache = Path(environ.get("XDG_CACHE_HOME") or home / ".cache")
    return cache / "ms-playwright"


def _only_starts_workers(config: pytest.Config) -> bool:
    """True for the controller of a parallel run, which runs no test itself."""
    return getattr(getattr(config, "option", None), "dist", "no") != "no"


def pytest_configure(config: pytest.Config) -> None:
    """Move the process to its own directories before it imports any test."""
    worker = getattr(config, "workerinput", None)
    if worker is None and _only_starts_workers(config):
        return
    label = "serial" if worker is None else worker["workerid"]
    tmp_path_root = os.environ.get(TMP_PATH_ROOT) or tempfile.gettempdir()
    browsers = installed_browsers(sys.platform, os.environ, Path(os.path.expanduser("~")))
    # Resolved: on macOS the temporary directory is reached through the
    # `/var` symlink, and `arena.private_paths.pinned_directory` opens a
    # private path component by component with O_NOFOLLOW.
    root = Path(tempfile.mkdtemp(prefix=f"arena-test-worker-{label}-")).resolve()
    # Exit handlers run newest first, and this one is registered before any
    # test module is imported, so it runs after every handler the product
    # registers. One of those (`mcp_client.client._atexit_stop_all`) creates
    # `<home>/arena-bridge/mcp/run` on the way out, which is how every worker
    # of every parallel run used to leave a directory behind. Registered
    # before the directories are made, so a failed setup is removed too.
    # A worker that is killed, or leaves through `os._exit`, runs no handler
    # and leaves its root in the temporary directory.
    atexit.register(_remove, root)
    values = private_directories(root)
    if worker is None:
        values[TMP_PATH_ROOT] = tmp_path_root
        if not os.environ.get(BROWSERS) and browsers.is_dir():
            values[BROWSERS] = str(browsers)
    config.stash[_MOVED] = (root, {name: os.environ.get(name) for name in values})
    os.environ.update(values)
    # `tempfile` remembers the first answer; make it ask the environment again.
    tempfile.tempdir = None


def pytest_unconfigure(config: pytest.Config) -> None:
    """Put the environment back and remove what the run left behind."""
    root, previous = config.stash.get(_MOVED, (None, {}))
    if root is None:
        return
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    tempfile.tempdir = None
    _remove(root)


def _remove(root: Path) -> None:
    """Remove the moved directories; called at teardown and again at exit."""
    # A handle still open on Windows keeps its file; the directory lives
    # under the temporary root either way, never in the account's home.
    shutil.rmtree(root, ignore_errors=True)
