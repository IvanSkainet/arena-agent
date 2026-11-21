"""T74: transport only environment variable names across pytest workers."""
from __future__ import annotations

from typing import Callable

import pytest

WORKER_ARENA_LEAKS = pytest.StashKey[list[str]]()


def publish_local_leaks(session, leaked, report: Callable) -> None:
    """Keep value-bearing controller diagnostics off the worker protocol."""
    if not leaked:
        return
    if hasattr(session.config, "workeroutput"):
        session.config.workeroutput["arena_environment_leaks"] = sorted({
            name for changed in leaked.values() for name in changed
        })
        return
    report(session, leaked)


def report_worker_leaks(session: pytest.Session) -> list[str]:
    """Report names from failed workers without interpreting values."""
    names = session.config.stash.get(WORKER_ARENA_LEAKS, [])
    if not names:
        return names
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return names
    reporter.write_sep("=", "ARENA_* environment leaked in workers", red=True)
    for name in sorted(set(names)):
        reporter.write_line(f"  {name}")
    return names


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error) -> None:
    """Propagate a worker leak refusal to its controller's stash."""
    names = getattr(node, "workeroutput", {}).get("arena_environment_leaks", [])
    if names:
        current = node.config.stash.get(WORKER_ARENA_LEAKS, [])
        node.config.stash[WORKER_ARENA_LEAKS] = [*current, *names]
