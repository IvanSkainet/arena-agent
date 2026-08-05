"""The mutation cache may save time; it may not lower the bar.

A full mutation run over ``arena/`` is ~103,000 mutants and ~26 CPU-hours,
and most of that re-proves results for code nobody touched. Caching is the
obvious fix and also the obvious way to accidentally stop testing, so the
properties that keep it honest are pinned here rather than assumed.

Measured on ``arena/files/sandbox.py``: cold run 146s, cached run 0s.

The three invariants:

* **The key covers everything that can change the verdict** -- the source,
  its guarding tests, and the mutmut version. Hashing only the source
  would let a weakened test suite ride on an old pass.
* **A miss is never a pass.** Unknown input means run it.
* **A hit still ratchets.** The cached survivor count goes through the
  same baseline comparison a fresh run would.

Sabotage record (mandatory per AGENTS.md):
  1. dropping the test files from the fingerprint
     -> test_editing_a_guarding_test_invalidates_the_entry fails.
  2. dropping the tool version
     -> test_a_different_mutmut_invalidates_the_entry fails.
  3. `lookup` returning a default entry on miss
     -> test_an_unknown_source_is_never_a_hit fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mutation_cache  # noqa: E402 -- needs the path line above


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A cache rooted in a throwaway tree with two real files."""
    root = tmp_path
    (root / "arena").mkdir()
    (root / "tests").mkdir()
    source = root / "arena" / "thing.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")
    guard = root / "tests" / "test_thing.py"
    guard.write_text("def test_f():\n    assert True\n", encoding="utf-8")

    monkeypatch.setattr(mutation_cache, "ROOT", root)
    monkeypatch.setattr(mutation_cache, "CACHE_FILE",
                        root / "scripts_mutation_cache.json")
    monkeypatch.setattr(mutation_cache, "tool_version", lambda: "mutmut 2.5.1")
    return root, "arena/thing.py", ("tests/test_thing.py",)


# ---------------------------------------------------------------------------
# What the key must cover.
# ---------------------------------------------------------------------------

def test_an_unchanged_input_is_a_hit(sandbox):
    _, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    entry = mutation_cache.lookup(source, tests)

    assert entry is not None
    assert entry["survived"] == 7
    assert entry["total"] == 100


def test_editing_the_source_invalidates_the_entry(sandbox):
    root, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    (root / source).write_text("def f():\n    return 2\n", encoding="utf-8")

    assert mutation_cache.lookup(source, tests) is None


def test_editing_a_guarding_test_invalidates_the_entry(sandbox):
    """The subtle one. Weakening a test must not ride on an old pass.

    If the key covered only the source, deleting assertions from the
    guarding test would keep the cached "all good" forever -- which is
    the exact regression mutation testing exists to catch.
    """
    root, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    (root / "tests" / "test_thing.py").write_text(
        "def test_f():\n    pass\n", encoding="utf-8")

    assert mutation_cache.lookup(source, tests) is None


def test_a_different_mutmut_invalidates_the_entry(sandbox, monkeypatch):
    """A different generator produces a different mutant set."""
    _, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    monkeypatch.setattr(mutation_cache, "tool_version", lambda: "mutmut 3.0.0")

    assert mutation_cache.lookup(source, tests) is None


def test_adding_a_guarding_test_invalidates_the_entry(sandbox):
    root, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    (root / "tests" / "test_extra.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8")

    assert mutation_cache.lookup(
        source, (*tests, "tests/test_extra.py")) is None


def test_a_missing_guard_test_does_not_hash_as_empty(sandbox):
    """A deleted test file must force a run, not resemble an empty one."""
    _, source, tests = sandbox

    present = mutation_cache.fingerprint(source, tests)
    absent = mutation_cache.fingerprint(source, ("tests/test_gone.py",))

    assert present != absent


# ---------------------------------------------------------------------------
# A miss is never a pass.
# ---------------------------------------------------------------------------

def test_an_unknown_source_is_never_a_hit(sandbox):
    _, _, tests = sandbox
    assert mutation_cache.lookup("arena/never_seen.py", tests) is None


def test_a_corrupt_cache_file_means_run_everything(sandbox):
    _, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)
    mutation_cache.CACHE_FILE.write_text("{ this is not json",
                                         encoding="utf-8")

    assert mutation_cache.lookup(source, tests) is None, (
        "a corrupt cache must degrade to 'test everything', not to "
        "'everything passed'"
    )


def test_a_truncated_cache_file_means_run_everything(sandbox):
    _, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)
    mutation_cache.CACHE_FILE.write_text("[]", encoding="utf-8")

    assert mutation_cache.lookup(source, tests) is None


def test_stale_lists_exactly_what_needs_running(sandbox):
    root, source, tests = sandbox
    targets = {source: tests}

    assert mutation_cache.stale(targets) == [source]

    mutation_cache.record(source, tests, survived=7, total=100)
    assert mutation_cache.stale(targets) == []

    (root / source).write_text("def f():\n    return 3\n", encoding="utf-8")
    assert mutation_cache.stale(targets) == [source]


# ---------------------------------------------------------------------------
# Provenance: a number with no history is a number nobody trusts.
# ---------------------------------------------------------------------------

def test_entries_record_how_they_were_obtained(sandbox):
    _, source, tests = sandbox
    mutation_cache.record(source, tests, survived=7, total=100)

    entry = json.loads(mutation_cache.CACHE_FILE.read_text())["entries"][source]

    assert entry["tests"] == list(tests)
    assert entry["tool"]
    assert entry["reason"]
    assert len(entry["fingerprint"]) == 64


def test_the_gate_still_compares_cached_results_to_the_baseline():
    """A hit must not bypass the ratchet -- that would be a way to pass
    by caching a good result and then breaking the code."""
    gate = (Path(__file__).resolve().parents[1]
            / "scripts" / "mutation_gate.py").read_text(encoding="utf-8")

    # The cached branch assigns into the same `results` dict the baseline
    # comparison reads from, rather than short-circuiting the function.
    assert "results[source] = survived" in gate
    assert "(cached)" in gate
    assert "MUTATION DEBT GREW" in gate
    cached_at = gate.index("(cached)")
    ratchet_at = gate.index("MUTATION DEBT GREW")
    assert cached_at < ratchet_at, (
        "the cached path must fall through to the baseline check"
    )
