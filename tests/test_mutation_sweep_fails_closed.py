"""The sweep must not report success when it measured nothing.

Sweep run #1 finished in 38 seconds, printed `ran 0 0 0` for all nine
targets, and the workflow went green. Two fail-opens stacked: the script
returned 0 unconditionally, and the workflow step carried
`continue-on-error: true`. A tool written to find fail-open code that is
itself fail-open is worse than no tool, because it hands out confidence.

Also covered: mutmut 2.5.1 rewrites the source file in place and only
restores it when it finishes. A cut-short sweep left
`"ok": True` mutated to `"XXokXX": True` in arena/admin/auto_update.py
in this workspace -- one `git add -A` away from shipping a mutant.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mutation_sweep.py"


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("mutation_sweep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def _run(argv: list[str], tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 -- fixed argv, no shell
        [sys.executable, str(SCRIPT), *argv,
         "--report", str(tmp_path / "r.md"),
         "--json", str(tmp_path / "r.json")],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )


def test_missing_mutmut_is_a_failure_not_a_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_sweep.py", "--report", str(tmp_path / "r.md"),
         "--json", str(tmp_path / "r.json")],
    )
    assert mod.main() == 1


def test_all_errors_means_exit_one(tmp_path, monkeypatch):
    """Sabotage: make every file error. Must go red, as sweep #1 did not."""
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/mutmut")
    monkeypatch.setattr(
        mod, "_run_one",
        lambda source, tests, timeout, curated=False: {"error": "zero mutants generated"},
    )
    monkeypatch.setattr(mod.mutation_cache, "lookup", lambda s, t: None)
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_sweep.py", "--report", str(tmp_path / "r.md"),
         "--json", str(tmp_path / "r.json")],
    )
    assert mod.main() == 1
    rows = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rows and all(r["status"] == "error" for r in rows)


def test_a_real_result_still_passes(tmp_path, monkeypatch):
    """Reverse sabotage: the guard must not redden a healthy sweep."""
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/mutmut")
    monkeypatch.setattr(
        mod, "_run_one",
        lambda source, tests, timeout, curated=False: {
            "survived": 3, "killed": 9, "total": 12, "seconds": 5},
    )
    monkeypatch.setattr(mod.mutation_cache, "lookup", lambda s, t: None)
    monkeypatch.setattr(mod.mutation_cache, "record", lambda *a, **k: None)
    # This test is about the exit code for a healthy sweep, so the
    # leaked-mutant check is stubbed out: run from a working tree with
    # any uncommitted edit -- which is the normal state while developing
    # -- it would otherwise fail for an unrelated and correct reason.
    # `test_a_mutant_left_on_disk_fails_the_sweep` covers the other side.
    monkeypatch.setattr(mod, "_leaked_mutants", lambda sources: [])
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_sweep.py", "--report", str(tmp_path / "r.md"),
         "--json", str(tmp_path / "r.json")],
    )
    assert mod.main() == 0


def test_deadline_marks_unrun_files_distinctly(tmp_path, monkeypatch):
    """An unreached file must never read like a file that came back clean."""
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/mutmut")
    # Drive the clock rather than racing it: a tiny wall-clock budget is
    # flaky, and a flaky gate teaches people to ignore gates.
    clock = iter([0.0] + [10_000.0] * 10_000)
    monkeypatch.setattr(mod.time, "time", lambda: next(clock))
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_sweep.py", "--deadline-minutes", "1",
         "--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")],
    )
    mod.main()
    rows = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    statuses = {r["status"] for r in rows}
    assert "not-reached-deadline" in statuses
    assert "ran" not in statuses


@pytest.mark.parametrize("shard", ["5/4", "0/4", "abc", "1/0", "-1/3", "3"])
def test_bad_shard_is_rejected(shard, tmp_path):
    """Exit 2 = "you called this wrong", distinct from 1 = "it failed".

    CI caught the first version of this: argument validation ran AFTER
    the mutmut-on-PATH check, so on a runner without mutmut a malformed
    --shard reported "mutmut is not installed" and exited 1 -- a
    different complaint about a different problem, and one that would
    send whoever hit it off installing a tool they did not need. Usage
    errors are now diagnosed before the environment is inspected, which
    is also why this test can run on a machine with no mutmut.
    """
    proc = _run(["--shard", shard], tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "shard" in (proc.stdout + proc.stderr).lower()


def test_a_valid_shard_is_not_rejected_as_malformed(tmp_path):
    """Reverse sabotage: the validator must not eat legitimate input."""
    proc = _run(["--shard", "2/4", "--deadline-minutes", "0.0001"], tmp_path)
    assert proc.returncode != 2, proc.stdout + proc.stderr


def test_shards_partition_the_target_list_exactly():
    """No file may be dropped between shards, and none run twice."""
    full = sorted(mod.discover_targets())
    for count in (2, 3, 4, 7):
        seen: list[str] = []
        for index in range(1, count + 1):
            seen.extend(full[index - 1::count])
        assert sorted(seen) == full
        assert len(seen) == len(set(seen))


def test_whole_tree_discovery_finds_far_more_than_the_gate():
    from mutation_gate import TARGETS

    found = mod.discover_targets()
    assert len(found) > 10 * len(TARGETS)
    assert all(k in found for k in TARGETS), "the gate's targets must survive"
    assert all(v == found[k] for k, v in TARGETS.items()), (
        "hand-written guard lists must win over the name-matched guess"
    )


def test_files_with_no_guard_are_reported_not_counted_clean():
    found = mod.discover_targets()
    unguarded = [k for k, v in found.items() if not v]
    assert unguarded, "expected some modules to have no name-matching test"
    # The status string for these is what keeps them out of the "clean"
    # bucket; assert the code path exists rather than trusting the name.
    assert "no-tests-declared" in SCRIPT.read_text(encoding="utf-8")


def test_source_is_restored_when_mutmut_is_interrupted(tmp_path, monkeypatch):
    """The in-place mutation must be rolled back on timeout.

    Reproduces the real incident: an interrupted run left a mutated
    literal in arena/admin/auto_update.py.
    """
    victim = ROOT / "arena" / "admin" / "auto_update.py"
    original = victim.read_bytes()

    def fake_run(argv, **kwargs):
        victim.write_bytes(original.replace(b'"ok"', b'"XXokXX"', 1))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    try:
        outcome = mod._run_one(
            "arena/admin/auto_update.py", ("tests/test_auto_update.py",),
            timeout=1,
        )
        assert "error" in outcome
        assert victim.read_bytes() == original
    finally:
        victim.write_bytes(original)


def test_workflow_does_not_swallow_the_sweep_exit_code():
    text = (ROOT / ".github" / "workflows" / "mutation-sweep.yml").read_text(
        encoding="utf-8"
    )
    assert "continue-on-error: true" not in text, (
        "the sweep step must be allowed to fail the run; sweep #1 was green "
        "while measuring nothing"
    )
    assert not re.search(r"^\s*run:\s*\|\s*\n\s*set -uo pipefail", text, re.M), (
        "use `set -euo pipefail` so a failing sweep fails the step"
    )


def test_a_mutant_left_on_disk_fails_the_sweep(tmp_path, monkeypatch):
    """The per-file restore is not enough on its own.

    mutmut can be killed outright -- job cancelled, OOM, runner gone --
    and then the mutant it had written just stays there. Not theoretical:
    an interrupted sweep in this workspace left `0 <= tab_index` rewritten
    to `1 <= tab_index` in arena/browser/cdp_client/tabs_http.py, and it
    surfaced hours later as an unrelated-looking test failure.
    """
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/mutmut")
    monkeypatch.setattr(
        mod, "_run_one",
        lambda source, tests, timeout, curated=False: {
            "survived": 1, "killed": 1, "total": 2, "seconds": 1},
    )
    monkeypatch.setattr(mod.mutation_cache, "lookup", lambda s, t: None)
    monkeypatch.setattr(mod.mutation_cache, "record", lambda *a, **k: None)
    monkeypatch.setattr(
        mod, "_leaked_mutants", lambda sources: ["arena/somewhere/leaked.py"]
    )
    monkeypatch.setattr(
        sys, "argv",
        ["mutation_sweep.py", "--report", str(tmp_path / "r.md"),
         "--json", str(tmp_path / "r.json")],
    )
    assert mod.main() == 1
    report = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "MUTANTS LEFT ON DISK" in report
    assert "leaked.py" in report


def test_an_unverifiable_tree_is_not_reported_as_clean(monkeypatch):
    """No git, or git failing, must not read as "nothing was modified"."""

    def boom(*args, **kwargs):
        raise OSError("git is not installed")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    leaked = mod._leaked_mutants(["arena/mobile/apk_paths.py"])
    assert leaked, "an unverifiable tree must not come back empty"


def test_the_leak_check_reads_real_git_state(tmp_path):
    """Reverse sabotage: it must report what git reports, not a constant.

    Asserting "a clean checkout yields []" would fail for anyone with
    uncommitted work in that file, so drive it against a file whose state
    is known: git itself is the oracle.
    """
    target = "arena/mobile/apk_paths.py"
    proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
        ["git", "diff", "--name-only", "--", target],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    expected = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert mod._leaked_mutants([target]) == expected
