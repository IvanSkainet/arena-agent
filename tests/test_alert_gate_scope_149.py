"""The alert gate could not be satisfied by fixing the code.

`security_alerts_check.py` asked GitHub for `state=open` across the whole
repository. That is right for a push to master and wrong for a pull
request: a finding on `master` fails every open PR, including the one
that removes it.

That is not hypothetical. Two `py/command-line-injection` alerts landed
on `master` with the #127 merge. The branch that deleted the `shell=True`
behind them (#149) sat blocked, because the gate kept reporting alerts
that live on the branch being merged *into*. Fixing the code could not
turn the check green; only merging could, and merging was what the check
was blocking. A gate with no path to green gets bypassed, and then it
protects nothing.

So on a pull request the query is scoped to that PR's head. Everywhere
else it stays repository-wide -- that is the mode which catches a finding
nobody has opened a PR for, and losing it would trade one blind spot for
another.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "security_alerts_check.py"


def _module():
    spec = importlib.util.spec_from_file_location("security_alerts_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gate():
    return _module()


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_a_pull_request_is_judged_on_its_own_head(gate, clean_env):
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_REF", "refs/pull/149/merge")

    assert gate.code_scanning_ref() == "refs/pull/149/head"


def test_the_merge_ref_is_not_used(gate, clean_env):
    """`refs/pull/N/merge` returns no alerts from this API -- a gate
    reading it would pass everything, which is worse than blocking."""
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_REF", "refs/pull/149/merge")

    assert gate.code_scanning_ref().endswith("/head")


def test_pull_request_target_reads_the_event_payload(gate, clean_env, tmp_path):
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps({"number": 77}), encoding="utf-8")
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    clean_env.setenv("GITHUB_EVENT_PATH", str(payload))

    assert gate.code_scanning_ref() == "refs/pull/77/head"


def test_the_event_decides_the_scope_not_the_ref_string(gate, clean_env):
    """Sabotage caught this: deleting the event check left every other
    test green.

    `GITHUB_REF` can read `refs/pull/N/merge` outside a pull request --
    a `push` triggered on a merge queue ref, a re-run, a workflow
    dispatched against one. If the ref string alone decided the scope,
    those runs would quietly narrow to one PR and stop reporting the
    repository, which is the exact blind spot this gate exists to close.
    """
    clean_env.setenv("GITHUB_EVENT_NAME", "push")
    clean_env.setenv("GITHUB_REF", "refs/pull/9/merge")

    assert gate.code_scanning_ref() is None, (
        "a non-PR event narrowed its scope because the ref looked like a PR"
    )


def test_a_push_to_master_still_sees_the_whole_repository(gate, clean_env):
    """The mode that catches a finding nobody has a PR for."""
    clean_env.setenv("GITHUB_EVENT_NAME", "push")
    clean_env.setenv("GITHUB_REF", "refs/heads/master")

    assert gate.code_scanning_ref() is None


@pytest.mark.parametrize("event", ["release", "schedule", "workflow_dispatch", ""])
def test_every_other_event_is_repository_wide(gate, clean_env, event):
    clean_env.setenv("GITHUB_EVENT_NAME", event)

    assert gate.code_scanning_ref() is None


def test_a_pull_request_with_no_discoverable_number_stays_wide(gate, clean_env):
    """Fail towards checking too much, never towards checking nothing.

    If the number cannot be found, the honest options are "scan
    everything" and "claim to be scoped while being unfiltered". The
    second is how a gate starts lying.
    """
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")

    assert gate.code_scanning_ref() is None


def test_an_unreadable_event_payload_does_not_crash_the_gate(gate, clean_env):
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_EVENT_PATH", "/definitely/not/here.json")

    assert gate.code_scanning_ref() is None


def test_a_corrupt_event_payload_does_not_crash_the_gate(gate, clean_env, tmp_path):
    payload = tmp_path / "event.json"
    payload.write_text("{not json", encoding="utf-8")
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_EVENT_PATH", str(payload))

    assert gate.code_scanning_ref() is None


def test_the_ref_actually_reaches_the_query(gate, clean_env, monkeypatch):
    """A scope nobody applies is a comment.

    `collect()` must put the ref in the URL it fetches, and must say so
    in its notes -- an operator reading "0 open" needs to know whether
    that was the repository or one branch.
    """
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_REF", "refs/pull/149/merge")

    seen = []

    def fake_get(path):
        seen.append(path)
        return [], ""

    monkeypatch.setattr(gate, "_get", fake_get)
    findings, notes = gate.collect()

    code_scanning = [p for p in seen if p.startswith("/code-scanning")]
    assert code_scanning, "the code-scanning feed was not queried at all"
    assert "ref=refs/pull/149/head" in code_scanning[0], code_scanning[0]
    assert any("scoped to" in n for n in notes), notes


def test_the_repository_wide_query_carries_no_ref(gate, clean_env, monkeypatch):
    clean_env.setenv("GITHUB_EVENT_NAME", "push")

    seen = []
    monkeypatch.setattr(gate, "_get", lambda path: (seen.append(path), ([], ""))[1])
    gate.collect()

    code_scanning = [p for p in seen if p.startswith("/code-scanning")]
    assert "ref=" not in code_scanning[0], code_scanning[0]


def test_the_other_two_feeds_are_never_scoped(gate, clean_env, monkeypatch):
    """Dependabot and secret scanning are repository facts.

    Scoping them to a branch would quietly stop reporting a leaked
    credential because the PR did not touch it.
    """
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_REF", "refs/pull/149/merge")

    seen = []
    monkeypatch.setattr(gate, "_get", lambda path: (seen.append(path), ([], ""))[1])
    gate.collect()

    for path in seen:
        if not path.startswith("/code-scanning"):
            assert "ref=" not in path, path


def test_the_ref_is_url_encoded(gate, clean_env, monkeypatch):
    """`refs/pull/N/head` has slashes; they must survive as slashes and
    nothing else may sneak through unescaped."""
    payload = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"number": "149 &evil"}, payload)
    payload.close()
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_EVENT_PATH", payload.name)

    seen = []
    monkeypatch.setattr(gate, "_get", lambda path: (seen.append(path), ([], ""))[1])
    try:
        gate.collect()
    finally:
        os.unlink(payload.name)

    code_scanning = [p for p in seen if p.startswith("/code-scanning")]
    assert " " not in code_scanning[0], code_scanning[0]
    assert "&evil" not in code_scanning[0].split("ref=")[-1], code_scanning[0]
