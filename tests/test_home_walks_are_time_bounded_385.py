"""The two `$HOME` walks must be bounded by the clock, not just by depth (#385).

`get_python_venvs` and `get_git_repos` crawl the home directory to depth
5 looking for `pyvenv.cfg` and `.git`. On the reporting machine that
cost 31.6s and 15.7s -- 54% of a 46-probe collection that was itself
brushing a 90-second timeout, which is how `/v1/hardware` came to take
81 seconds and the dashboard came to sit on "Loading hardware data..."
forever (#380).

The depth limit bounds how *deep* the walk goes, not how *long* it
takes: a wide home directory, with Windows Defender in the `stat` path,
is unbounded in practice. A time budget bounds it directly.

Partial results are the intended trade. These probes exist so an agent
can spot an existing venv or an uncommitted repo; fifteen found in two
seconds beat all of them found in thirty. What must not happen is a
partial result that looks complete, so `truncated` is set explicitly.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from arena.inventory import probe_agent_ctx as ctx


@pytest.fixture
def wide_tree(tmp_path: Path) -> Path:
    """A directory tree with nothing to find -- the pathological shape.

    Wide rather than deep: depth is already capped at 5, so a deep tree
    would prove nothing. Breadth is what the old code had no answer to.
    """
    for a in range(12):
        for b in range(12):
            (tmp_path / f"d{a}" / f"e{b}" / "f").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _pin_budget(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Force every `_Budget` in this test to the given ceiling.

    Patching the constructor rather than the module constant: the
    constant is read as a default argument, so rebinding it after
    import would not reach `_Budget()` calls that pass nothing.
    """
    original = ctx._Budget.__init__

    def fixed(self, _seconds: float = seconds) -> None:
        original(self, seconds)

    monkeypatch.setattr(ctx._Budget, "__init__", fixed)


def test_the_venv_walk_stops_when_the_budget_is_spent(
        wide_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect: a wide tree could walk for as long as it liked."""
    _pin_budget(monkeypatch, 0.001)

    started = time.monotonic()
    result = ctx.get_python_venvs(scan_root=str(wide_tree))
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, (
        f"the walk took {elapsed:.2f}s with a 1ms budget; it is not "
        "checking the deadline")
    assert result["truncated"] is True
    assert "0.001" in result["truncated_reason"], result["truncated_reason"]


def test_the_git_walk_stops_when_the_budget_is_spent(
        wide_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same bound on the other walk, which had the same shape."""
    _pin_budget(monkeypatch, 0.001)

    started = time.monotonic()
    ctx.get_git_repos(scan_root=str(wide_tree))
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, (
        f"the walk took {elapsed:.2f}s with a 1ms budget")


def test_a_complete_scan_is_not_marked_truncated(tmp_path: Path) -> None:
    """The control, and the one that stops this becoming a lie.

    Every assertion above is satisfied by a probe that always reports
    `truncated`. A scan that finishes inside its budget must say so, or
    the flag carries no information.
    """
    (tmp_path / "small").mkdir()

    result = ctx.get_python_venvs(scan_root=str(tmp_path))

    assert result.get("truncated") is None, result
    assert result.get("truncated_reason") is None, result


def test_a_venv_inside_the_budget_is_still_found(tmp_path: Path) -> None:
    """Bounding the walk must not stop it doing its job.

    Without this, "return immediately and mark it truncated" would pass
    every other test in this file.
    """
    venv = tmp_path / "project" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr\nversion = 3.13.0\n",
                                     encoding="utf-8")
    (venv / "bin" / "python").write_text("", encoding="utf-8")

    result = ctx.get_python_venvs(scan_root=str(tmp_path))

    assert result["available"] is True
    assert [v["path"] for v in result["venvs"]] == [str(venv)]


def test_two_concurrent_walks_do_not_expire_each_other(
        wide_tree: Path) -> None:
    """The budget is per walk, not a module-level deadline.

    Inventory probes run concurrently in one process (#386). A shared
    deadline would mean the first walk to start decides when the second
    one dies -- and the second would report `truncated` having barely
    run. Each `_Budget` instance owns its own deadline; this pins that.
    """
    first = ctx._Budget(seconds=10.0)
    second = ctx._Budget(seconds=0.0)

    assert second.spent() is True
    assert first.spent() is False, (
        "expiring one budget expired another; the deadline is shared")


def test_the_budget_is_checked_between_siblings_not_only_between_levels(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One flat directory with many entries must still be interruptible.

    The guard at the top of `_walk` only fires when descending a level,
    so a home directory that is *wide* rather than deep would run to
    completion however long it took.

    Getting this test right took three attempts, and the failures are
    instructive. A budget that is already spent proves nothing: the
    outer guard returns before the loop starts, so the in-loop check is
    never reached and removing it changes nothing. The budget has to
    expire *during* the loop. Here each entry costs 2ms against a 50ms
    budget, so the walk should stop around entry 25 of 400 -- measured,
    23 with the check and all 400 without it.
    """
    for i in range(400):
        (tmp_path / f"s{i}").mkdir()

    seen = {"n": 0}
    real_is_dir = Path.is_dir

    def slow_is_dir(self) -> bool:
        seen["n"] += 1
        time.sleep(0.002)
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", slow_is_dir)
    _pin_budget(monkeypatch, 0.05)

    ctx.get_python_venvs(scan_root=str(tmp_path))

    assert seen["n"] < 200, (
        f"the walk inspected {seen['n']} of 400 entries after its budget "
        "expired; the deadline is only checked when descending a level, so "
        "a wide directory runs to completion")
