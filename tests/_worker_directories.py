"""Give every xdist worker per-user and temporary directories of its own."""

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
# single test module, which is before any of those constants is bound. The
# serial run is left as it is: one process has nobody to share with.
#
# The variables are exactly the ones `arena/governance/benchmark_runner.py`
# makes private for a measured run, so the two kinds of run agree. As there, the
# home and the temporary directory are siblings: a home *inside* the temporary
# directory is what the autostart repair refuses to install from (#381).
#
# `tmp_path` is not moved. The controller hands each worker its base directory
# explicitly, and pytest already names it per worker.

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

#: Where a program looks for "my files" and "scratch space" when nothing more
#: specific is set.
PRIVATE = ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
           "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")

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
    return values


def pytest_configure(config: pytest.Config) -> None:
    """Move a worker to its own directories before it imports any test."""
    worker = getattr(config, "workerinput", None)
    if worker is None:
        return
    # Resolved: on macOS the temporary directory is reached through the
    # `/var` symlink, and `arena.private_paths.pinned_directory` opens a
    # private path component by component with O_NOFOLLOW.
    root = Path(tempfile.mkdtemp(prefix=f"arena-test-worker-{worker['workerid']}-")).resolve()
    values = private_directories(root)
    config.stash[_MOVED] = (root, {name: os.environ.get(name) for name in values})
    os.environ.update(values)
    # `tempfile` remembers the first answer; make it ask the environment again.
    tempfile.tempdir = None


def pytest_unconfigure(config: pytest.Config) -> None:
    """Put the environment back and remove what the worker left behind."""
    root, previous = config.stash.get(_MOVED, (None, {}))
    if root is None:
        return
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    tempfile.tempdir = None
    # A handle still open on Windows keeps its file; the directory lives
    # under the temporary root either way, never in the account's home.
    shutil.rmtree(root, ignore_errors=True)
