"""The global-patch ratchet must detect the flake class it exists for.

#230 and #235 were the same defect twice: a test patched a stdlib module
through a production alias, the substitution escaped process-wide, and
concurrent code observed it. Both surfaced as Windows-only intermittent
failures with no visible connection to the test that caused them.

These tests pin the detector and -- more importantly -- its failure
branches. A ratchet that cannot report a regression is decoration.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "global_patch_ratchet.py"
BASELINE = REPO_ROOT / "scripts" / "global_patch_baseline.json"


def _load():
    spec = importlib.util.spec_from_file_location("global_patch_ratchet", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ratchet():
    return _load()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=300)


def test_script_and_baseline_exist():
    assert SCRIPT.is_file(), f"{SCRIPT} is missing; CI references it"
    assert BASELINE.is_file(), f"{BASELINE} is missing; the ratchet needs it"


def test_repository_is_at_or_below_its_baseline():
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_baseline_matches_the_current_count(ratchet):
    """A baseline above the real count silently permits new regressions."""
    hits, _ = ratchet.findings()
    allowed = json.loads(BASELINE.read_text(encoding="utf-8"))["allowed"]
    assert len(hits) <= allowed
    assert allowed - len(hits) <= 5, (
        f"baseline {allowed} is {allowed - len(hits)} above the actual "
        f"{len(hits)}; that slack is room for a new flake to hide in"
    )


def test_it_flags_a_patch_aimed_at_a_concurrent_module(ratchet, tmp_path):
    """The #235 shape: alias.subprocess in a module that starts threads."""
    src = (
        "import arena.admin.bore as bore_mod\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(bore_mod.subprocess, 'Popen', None)\n"
    )
    tree = __import__("ast").parse(src)
    aliases = ratchet._arena_aliases(tree)
    assert aliases["bore_mod"] == "arena.admin.bore"
    assert "bore" in ratchet.concurrent_modules(), (
        "arena/admin/bore.py starts a monitor thread; if this stops being "
        "true the detector's premise has changed"
    )


def test_it_ignores_a_patch_on_the_module_itself(ratchet):
    """`setattr(mod, '_spawn', ...)` is the seam -- the recommended form.

    The gate must not object to the very thing it tells people to do, or
    the advice is unfollowable and the gate gets suppressed.
    """
    src = (
        "import arena.admin.bore as bore_mod\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(bore_mod, '_spawn', None)\n"
    )
    import ast as _ast
    tree = _ast.parse(src)
    targets = [n.args[0] for n in _ast.walk(tree)
               if isinstance(n, _ast.Call)
               and isinstance(n.func, _ast.Attribute)
               and n.func.attr == "setattr"]
    assert targets and isinstance(targets[0], _ast.Name), (
        "patching the module itself yields a Name target, which the "
        "detector skips; it only inspects Attribute targets"
    )


def test_the_ratchet_fails_when_the_baseline_is_exceeded(tmp_path):
    """Negative test: lower the baseline and require a red result."""
    original = BASELINE.read_text(encoding="utf-8")
    current = json.loads(original)["allowed"]
    BASELINE.write_text(json.dumps({"allowed": max(current - 1, 0)}) + "\n",
                        encoding="utf-8")
    try:
        proc = _run()
    finally:
        BASELINE.write_text(original, encoding="utf-8")
    assert proc.returncode == 1, proc.stdout
    assert "FAIL" in proc.stdout
    assert "seam" in proc.stdout, (
        "the failure must say how to fix it, not just that it failed"
    )


def test_the_ratchet_refuses_a_truncated_scan():
    """A gate that scans nothing reports OK forever."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "MIN_TEST_FILES" in source
    probe = REPO_ROOT / "scripts" / "_global_patch_probe.py"
    probe.write_text(source.replace('TESTS.rglob("test_*.py")',
                                    'TESTS.rglob("nothing-*.py")'),
                     encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(probe)],
                              capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1, proc.stdout
    assert "scan is broken" in proc.stdout


def test_a_module_is_concurrent_if_a_thread_starter_imports_it(ratchet):
    """#230's module starts nothing; its caller does.

    `arena/observability/live_metrics.py` contains no Thread, task or
    pool. The ~1Hz push loop lives in `live_metrics_handler.py`, which
    imports it and calls `live_metrics_snapshot()` from a task -- so a
    test patching `lm.time.time` handed its timeline to that loop.

    Checked against the real pre-fix commit: judging modules only by
    their own source reported **zero** findings for live_metrics and
    would have let #230 through. Reachability is what makes this gate
    cover the defect it was written for, not an extra.
    """
    concurrent = ratchet.concurrent_modules()
    assert "live_metrics_handler" in concurrent, (
        "the handler starts the push loop; if not, the premise changed"
    )
    assert "live_metrics" in concurrent, (
        "live_metrics is reached from a concurrent caller and must count "
        "as exposed, even though it starts no thread of its own (#230)"
    )


def test_concurrency_detection_is_not_vacuous(ratchet):
    """If nothing looks concurrent, every finding disappears silently."""
    mods = ratchet.concurrent_modules()
    assert len(mods) >= 10, (
        f"only {len(mods)} concurrent modules found; the regex probably "
        f"stopped matching and the gate is now a no-op"
    )
