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

import json
import os
import pathlib
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "security_alerts_check.py"
MODULE = ROOT / "arena" / "security_alerts.py"


def _module():
    """The gate under test.

    #190 moved the logic out of the `scripts/` entrypoint into
    `arena.security_alerts`; the script is now a thin wrapper. These
    tests follow the decisions, so they import the module rather than
    exec'ing the file by path.
    """
    import arena.security_alerts as gate_module

    return gate_module


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
    _, notes = gate.collect()

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


# --- review found two ways to crash the gate; one was real ----------------

@pytest.mark.parametrize("payload", ["[]", '"a string"', "42", "null"])
def test_valid_json_of_the_wrong_shape_does_not_crash_the_gate(
    gate, clean_env, tmp_path, payload
):
    """Reported by Qodo, reproduced, real.

    `json.load(fh).get("number")` raises AttributeError on a list or a
    string -- valid JSON, wrong shape, and not a `ValueError`, so the
    existing handler missed it. A security gate must not be crashable by
    the contents of a file it merely consults; a crashed job reads as
    "failed", and the fix for a failing security check is not obvious to
    whoever looks next.
    """
    event = tmp_path / "event.json"
    event.write_text(payload, encoding="utf-8")
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_EVENT_PATH", str(event))

    assert gate.code_scanning_ref() is None


@pytest.mark.parametrize("ref", ["refs/pull/", "refs/pull", "refs/pull//", "refs/"])
def test_a_truncated_ref_does_not_crash_the_gate(gate, clean_env, ref):
    """Also reported, as an IndexError. It was not reachable.

    `startswith("refs/pull/")` guarantees three segments, so `[2]` is
    `""` and never raises; `refs/pull` without the trailing slash fails
    the prefix check and never reaches the split. Verified both ways
    before changing anything -- sabotage confirms it: restoring the
    "unsafe" `ref.split("/")[2]` keeps every test green, because there
    is no input that reaches it badly.

    Kept as a test of the behaviour that matters: a truncated ref must
    produce a repository-wide scan, not a scoped one.
    """
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_REF", ref)

    assert gate.code_scanning_ref() is None


@pytest.mark.parametrize("number", ["a&b", "1 OR 1", "../../master", "", " "])
def test_a_non_numeric_pr_number_is_refused(gate, clean_env, tmp_path, number):
    """A PR number is digits. Anything else builds a ref that matches
    nothing, and a query matching nothing returns zero alerts -- which
    reads exactly like a clean repository."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"number": number}), encoding="utf-8")
    clean_env.setenv("GITHUB_EVENT_NAME", "pull_request")
    clean_env.setenv("GITHUB_EVENT_PATH", str(event))

    assert gate.code_scanning_ref() is None


# --- #190: the script must stay a wrapper, not grow the gate back --------

def test_the_entrypoint_stays_a_thin_wrapper() -> None:
    """The boundary #190 exists to hold.

    A qodo review on PR #189 named it: a `scripts/` file that does its
    own networking, alert processing and severity decisions is not an
    entrypoint, it is the application with a shebang. The logic moved to
    `arena/security/alerts.py`; this keeps it from drifting back one
    convenient helper at a time.
    """
    import ast

    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)

    functions = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert functions == [], (
        f"the entrypoint defines {functions!r}; gate logic belongs in "
        "arena/security_alerts.py"
    )
    assert "urllib" not in source, "the entrypoint does its own networking again"
    assert "arena.security_alerts" in source, (
        "the entrypoint no longer delegates to the module"
    )


def test_the_entrypoint_still_runs_as_a_script(tmp_path) -> None:
    """CI, preflight and security-scan.yml all invoke it by path.

    Importable-but-not-runnable would be a silent break: the module
    tests would stay green while every pipeline that shells out to the
    path failed on an ImportError.
    """
    import subprocess  # nosec B404 -- fixed argv, no shell; running the entrypoint IS the test
    import sys

    # An empty string, not a credential: the point is to clear both
    # variables so the gate takes its no-token path. bandit's B105
    # pattern-matches the name, not the value.
    no_token = ""  # nosec B105 -- clears the variable, not a secret
    proc = subprocess.run(  # nosec B603 -- fixed argv, no shell  # nosemgrep: dangerous-subprocess-use-audit -- argv is [sys.executable, a repo-relative constant, two literals]; same rationale as the bandit nosec on this line
        [sys.executable, str(SCRIPT), "--max-severity", "medium"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "GITHUB_TOKEN": no_token, "GH_TOKEN": no_token},
        cwd=str(tmp_path),
        # The exit code IS the assertion below; raising on it here would
        # turn a legible failure into a CalledProcessError traceback.
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SKIPPED" in proc.stdout, proc.stdout


def test_the_gate_module_does_not_shadow_arena_security() -> None:
    """`arena/security.py` already exists, and start-up depends on it.

    The first attempt at #190 put the gate in `arena/security/alerts.py`.
    A package of that name shadows the module, and every job in the
    matrix died before collecting a single test:

        File "arena/runtime_deps/core.py", line 160, in <module>
            from arena.security import (
        ImportError: cannot import name '_INPUT_INJECTION_PATTERNS'
        from 'arena.security'

    `unified_bridge` imports that through `arena.runtime_deps.core` at
    start-up, so the failure was total and instant -- which was lucky.
    A partial shadow would have been a subtle one. The gate is a flat
    `arena/security_alerts.py`, alongside `security_http.py`,
    `security_ssrf.py` and `security_input.py`.
    """
    import arena.security

    assert not (ROOT / "arena" / "security").is_dir(), (
        "a arena/security/ package shadows arena/security.py, which "
        "unified_bridge imports at start-up"
    )
    assert hasattr(arena.security, "_INPUT_INJECTION_PATTERNS"), (
        "arena.security no longer resolves to the module runtime_deps.core "
        "imports from"
    )
    assert MODULE.is_file(), f"the gate module is missing at {MODULE}"
