"""#521: the request log and the bridge log are state, kept beside the audit log and not beside the code."""
from __future__ import annotations

import json
import logging
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import unified_bridge as ub
from arena import constants
from arena.bootstrap_logging import OwnerOnlyRotatingFileHandler, setup_logging
from arena.home import agent_home, code_root
from arena.observability.log_cleanup import LogCleanupContext, make_log_cleanup_runtime
from arena.wiring.base_runtime import build_base_runtime
from arena.wiring.observability_runtime import build_observability_runtimes
from arena.wiring.runtime_wrappers import build_runtime_wrappers

REPO = Path(__file__).resolve().parents[1]
POSIX_MODES = pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps access in ACLs; a POSIX mode there says nothing")


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture(name="permissive_umask")
def _permissive_umask():
    """The common default, under which a plain open() makes a file everyone can read."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.fixture(name="unconfigured_logger")
def _unconfigured_logger(monkeypatch):
    """The bridge logger as a starting process finds it, with whatever it opens closed afterwards."""
    logger = logging.getLogger("arena-bridge")
    opened: list[logging.Handler] = []
    monkeypatch.setattr(logger, "handlers", opened)
    yield logger
    for handler in opened:
        handler.close()


def test_both_logs_are_kept_beside_the_audit_log():
    """One rule for all three: an install that keeps its state beside the code keeps its logs there too."""
    assert {constants.REQUEST_LOG.parent, constants.BRIDGE_LOG.parent} == {constants.AUDIT.parent}


@pytest.mark.parametrize("name", ["REQUEST_LOG", "BRIDGE_LOG"])
def test_under_the_suite_neither_log_is_in_the_checkout(name):
    """Every worker has its own agent home; a log in the repository would be shared by all of them."""
    if agent_home() == code_root():
        pytest.skip("this checkout is the agent home (it holds earlier state, or was named as one), so its logs belong here")
    assert REPO not in getattr(constants, name).resolve().parents


@pytest.fixture(name="separated")
def _separated(tmp_path, monkeypatch):
    """The bridge's namespace with the code in one directory and the two logs declared in another."""
    code, state, user = tmp_path / "code", tmp_path / "state", tmp_path / "user"
    for directory in (code, state, user):
        directory.mkdir()
    # The startup cleanup also looks for service logs under the account's home
    # and the agent home; without xdist those are the developer's own.
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("ARENA_AGENT_HOME", str(state))
    values = dict(vars(ub))
    values.update(APP_DIR=code, BRIDGE_LOG=state / "bridge.log", REQUEST_LOG=state / "requests.jsonl", AUDIT=state / "audit.jsonl")
    return values


def test_a_served_request_is_written_to_the_declared_log(separated):
    """The bridge's own writer, as wired: this is what appended to the code directory before."""
    build_runtime_wrappers(separated)["_log_request_response"]("GET", "/v1/probe-521", 200, 0.001, "probe-521")
    written = separated["REQUEST_LOG"].read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["req_id"] for line in written] == ["probe-521"]
    assert list(separated["APP_DIR"].iterdir()) == []


def test_startup_cleanup_rotates_the_declared_logs_and_no_others(separated):
    """Oversized logs are rotated where they are declared; same-named files beside the code are not logs."""
    code = separated["APP_DIR"]
    for name in ("bridge.log", "requests.jsonl"):
        (separated["AUDIT"].parent / name).write_text("oversized", encoding="utf-8")
        (code / name).write_text("not a log", encoding="utf-8")
    separated["make_log_cleanup_runtime"] = lambda ctx: make_log_cleanup_runtime(replace(ctx, max_log_size=8))
    build_observability_runtimes(separated)["_rotate_all_logs_on_startup"]()
    assert sorted(path.name for path in separated["AUDIT"].parent.iterdir()) == ["bridge.log.1", "requests.jsonl.1"]
    assert sorted(path.name for path in code.iterdir()) == ["bridge.log", "requests.jsonl"]


def test_the_reader_and_the_writer_share_one_file():
    """The request-log endpoint reads what the middleware wrote."""
    assert ub._REQ_LOG_FILE == constants.REQUEST_LOG


def test_the_bridge_log_is_opened_where_it_is_declared(tmp_path):
    """And its directory is the one created for it: a fresh agent home does not exist yet."""
    opened = {}
    declared = tmp_path / "state" / "bridge.log"
    runtime = build_base_runtime({
        "BRIDGE_DIR": tmp_path,
        "BRIDGE_LOG": declared,
        "_setup_logging_runtime": lambda **kwargs: opened.update(kwargs) or logging.getLogger("probe-521"),
    })
    for name in ("_EXECUTOR", "_SLOW_EXECUTOR"):
        runtime[name].shutdown()
    assert opened == {"app_dir": declared.parent, "log_file": declared}
    assert runtime["LOG_FILE"] == declared


@POSIX_MODES
def test_a_fresh_agent_home_and_its_bridge_log_are_private_from_the_start(tmp_path, permissive_umask, unconfigured_logger):
    """Logging is the first thing to touch a fresh agent home, before the audit log makes it private."""
    home = tmp_path / "arena-bridge"
    setup_logging(app_dir=home, log_file=home / "bridge.log")
    unconfigured_logger.info("written")
    assert (_mode(home), _mode(home / "bridge.log")) == (0o700, 0o600)


@POSIX_MODES
def test_a_rollover_leaves_both_the_new_log_and_the_rotated_copy_private(tmp_path, permissive_umask):
    """The handler reopens its file after rotating, and a plain reopen would be 0644."""
    log_file = tmp_path / "bridge.log"
    handler = OwnerOnlyRotatingFileHandler(str(log_file), maxBytes=1024, backupCount=2, encoding="utf-8")
    try:
        handler.emit(logging.makeLogRecord({"msg": "before"}))
        handler.doRollover()
        handler.emit(logging.makeLogRecord({"msg": "after"}))
    finally:
        handler.close()
    assert (_mode(log_file), _mode(f"{log_file}.1")) == (0o600, 0o600)
    assert "before" in Path(f"{log_file}.1").read_text(encoding="utf-8")


@POSIX_MODES
def test_a_log_that_was_readable_by_everyone_is_narrowed_when_it_is_opened(tmp_path):
    """An install upgraded in place already has a 0644 bridge.log."""
    log_file = tmp_path / "bridge.log"
    log_file.write_text("old\n", encoding="utf-8")
    log_file.chmod(0o644)
    OwnerOnlyRotatingFileHandler(str(log_file), encoding="utf-8").close()
    assert _mode(log_file) == 0o600


def test_logging_still_starts_where_the_directory_cannot_be_made_private(tmp_path, monkeypatch, unconfigured_logger):
    """No private directory is a lesser loss than no log."""
    def refuse(path):
        raise OSError("directory descriptors unavailable")

    monkeypatch.setattr("arena.bootstrap_logging.private_directory", refuse)
    home = tmp_path / "arena-bridge"
    setup_logging(app_dir=home, log_file=home / "bridge.log")
    unconfigured_logger.info("written")
    assert "written" in (home / "bridge.log").read_text(encoding="utf-8")


@POSIX_MODES
def test_the_disk_that_is_watched_is_the_one_the_logs_fill(tmp_path, monkeypatch):
    """The agent home need not be on the disk that holds the code."""
    asked = []
    code, state = tmp_path / "code", tmp_path / "state"

    def usage(path):
        asked.append(path)
        return os.statvfs_result((4096, 4096, 100, 25, 25, 0, 0, 0, 0, 255))

    monkeypatch.setattr(os, "statvfs", usage)
    runtime = make_log_cleanup_runtime(LogCleanupContext(app_dir=code, log_files=[state / "bridge.log"], disk_dir=state))
    assert (runtime.check_disk_space(), asked) == (75.0, [str(state)])
