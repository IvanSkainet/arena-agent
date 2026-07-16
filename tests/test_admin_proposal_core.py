"""Core tests for arena.admin.proposal (v4.19.0).

Covers the pure-logic layer (pre-flight filters, state machine,
JSONL ledger) and the git worktree plumbing against a real
temporary repo. HTTP handlers are covered in a follow-up test
file once wire is in place.

The v4.19.0 feature is deliberately conservative: agents can
submit diffs, they land on branches, tests decide pass/fail,
push is manual (or v4.20 optional). This test file exists to
prove the safety-critical invariants BEFORE we expose the HTTP
surface:

* diffs mentioning token.txt / .env / .git/config are refused
* rejected proposals never touch git
* worktrees live outside the running checkout
* apply failures don't corrupt the main branch
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.proposal import (   # noqa: E402
    BRANCH_PREFIX,
    Proposal,
    ProposalStore,
    STATE_QUEUED, STATE_APPLYING, STATE_TESTING,
    STATE_PASSED, STATE_FAILED, STATE_REJECTED,
    apply_diff,
    commit_proposal,
    create_worktree,
    cleanup_worktree,
    validate_diff,
    validate_metadata,
)


# ---------------------------------------------------------------------------
# Pre-flight filters
# ---------------------------------------------------------------------------

def test_validate_diff_rejects_empty_and_whitespace():
    assert validate_diff("")[0] is False
    assert validate_diff("   \n\n\n")[0] is False


def test_validate_diff_accepts_ordinary_patch():
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-hello\n"
        "+hi\n"
    )
    ok, reason = validate_diff(diff)
    assert ok, reason


def test_validate_diff_rejects_over_cap():
    """A diff bigger than the 512 KiB cap is refused up-front so
    a runaway agent can't fill the disk before we notice."""
    huge = "diff --git a/x b/x\n" + ("A" * (600 * 1024))
    ok, reason = validate_diff(huge)
    assert not ok
    assert "too large" in reason


@pytest.mark.parametrize("path", [
    "token.txt", "authtoken.secret", ".env",
    ".git/config", ".git/credentials", ".netrc",
    "arena/constants.py", "pyproject.toml",
    "audit.jsonl",
])
def test_validate_diff_rejects_blocked_paths(path):
    """Substring pre-scan must fire even when the diff header is
    malformed -- an agent trying to smuggle a token change past
    us via a comment mentioning ``token.txt`` in a Python file
    is refused too."""
    diff = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -1 +1 @@\n-old\n+new\n"
    )
    ok, reason = validate_diff(diff)
    assert not ok, f"blocked path {path!r} slipped through"
    assert "block" in reason.lower()


def test_validate_diff_rejects_ssh_key_path():
    """Blocklist is broad: .ssh/ or .aws/credentials mentioned
    anywhere in a diff header is refused."""
    diff = (
        "diff --git a/home/user/.ssh/id_rsa b/home/user/.ssh/id_rsa\n"
        "--- /dev/null\n+++ b/home/user/.ssh/id_rsa\n"
        "@@ -0,0 +1 @@\n+ssh-rsa AAAA\n"
    )
    ok, reason = validate_diff(diff)
    assert not ok
    assert ".ssh" in reason


def test_validate_diff_rejects_blocked_content_even_in_body():
    """Substring scan is intentionally paranoid -- a diff that
    edits an unrelated file but PATCHES IN a line containing
    ``token.txt`` is also refused. False-positive is a rejected
    proposal (agent tries again); false-negative is a leaked
    secret."""
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " hello\n"
        "+see token.txt for details\n"
    )
    ok, reason = validate_diff(diff)
    assert not ok


def test_validate_metadata_requires_title_and_rationale():
    assert validate_metadata("", "why")[0] is False
    assert validate_metadata("what", "")[0] is False
    assert validate_metadata("  ", "  ")[0] is False
    ok, _ = validate_metadata("Fix typo in help", "Extra 'the the' repeat")
    assert ok


def test_validate_metadata_rejects_over_cap():
    ok, reason = validate_metadata("A" * 300, "why")
    assert not ok
    assert "title too long" in reason
    ok, reason = validate_metadata("t", "R" * 5000)
    assert not ok
    assert "rationale too long" in reason


# ---------------------------------------------------------------------------
# JSONL ProposalStore
# ---------------------------------------------------------------------------

def _sample_proposal(rid="deadbeef1234", state=STATE_QUEUED):
    return Proposal(
        request_id=rid,
        title="Fix typo",
        rationale="Extra 'the the' repeat.",
        diff_bytes=42,
        diff_sha256="a" * 64,
        branch=f"{BRANCH_PREFIX}{rid[:8]}",
        state=state,
    )


def test_store_append_and_load_latest(tmp_path):
    st = ProposalStore(tmp_path / "proposals.jsonl")
    p = _sample_proposal(rid="aaaabbbb1111")
    st.append(p)
    p.state = STATE_APPLYING
    st.append(p)
    p.state = STATE_PASSED
    p.exit_code = 0
    st.append(p)

    latest = st.load_latest("aaaabbbb1111")
    assert latest is not None
    assert latest["state"] == STATE_PASSED
    assert latest["exit_code"] == 0


def test_store_load_latest_missing_returns_none(tmp_path):
    st = ProposalStore(tmp_path / "proposals.jsonl")
    assert st.load_latest("nope") is None
    # After a write, an unrelated id still returns None.
    st.append(_sample_proposal(rid="aaaa"))
    assert st.load_latest("bbbb") is None


def test_store_list_recent_deduplicates_by_id_newest_first(tmp_path):
    st = ProposalStore(tmp_path / "proposals.jsonl")
    for rid in ("aaaa1111", "bbbb2222", "cccc3333"):
        p = _sample_proposal(rid=rid)
        st.append(p)
        p.state = STATE_TESTING
        st.append(p)   # duplicate id, different state
    listed = st.list_recent(limit=10)
    ids = [r["request_id"] for r in listed]
    assert ids == ["cccc3333", "bbbb2222", "aaaa1111"]   # newest first
    # Latest state per id, not the first append.
    assert all(r["state"] == STATE_TESTING for r in listed)


def test_store_list_recent_respects_limit(tmp_path):
    st = ProposalStore(tmp_path / "proposals.jsonl")
    for i in range(30):
        st.append(_sample_proposal(rid=f"id{i:06d}"))
    assert len(st.list_recent(limit=5)) == 5
    # Sanity clamp on absurd values -- we cap at 200 internally.
    assert len(st.list_recent(limit=100000)) == 30
    assert len(st.list_recent(limit=0)) == 1   # min clamp = 1


def test_store_survives_corrupt_line(tmp_path):
    """A junk line in the middle of the ledger must not break
    subsequent reads. Append-only files can pick up torn writes
    on power loss; the reader has to be tolerant."""
    p = tmp_path / "proposals.jsonl"
    p.write_text(
        '{"request_id":"aaaa","state":"queued"}\n'
        'garbage-not-json\n'
        '{"request_id":"aaaa","state":"passed"}\n',
        encoding="utf-8",
    )
    st = ProposalStore(p)
    assert st.load_latest("aaaa")["state"] == "passed"


# ---------------------------------------------------------------------------
# Git plumbing -- real subprocess.run against a temp repo
# ---------------------------------------------------------------------------

def _init_temp_repo(tmp_path) -> Path:
    """Create a minimal git repo with one committed file so
    we have something to branch off of."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "master"],
        ["git", "config", "user.email", "t@t.local"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, check=True,
                       capture_output=True, timeout=10)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True,
                   capture_output=True, timeout=10)
    subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=repo,
                   check=True, capture_output=True, timeout=10)
    return repo


def test_create_worktree_makes_branch_outside_main_checkout(tmp_path):
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, err = create_worktree(repo, home, "deadbeef1234")
    assert err is None, err
    assert wt is not None
    # Worktree is UNDER bridge_home, NOT under the main repo --
    # that's the whole point.
    assert str(wt).startswith(str(home))
    assert (wt / "README.md").exists()
    # And a new branch was created off HEAD.
    r = subprocess.run(["git", "-C", str(repo), "branch"],
                       capture_output=True, text=True, timeout=10)
    assert "proposal/deadbeef" in r.stdout


def test_create_worktree_refuses_duplicate(tmp_path):
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, err = create_worktree(repo, home, "aaaa1111zzzz")
    assert err is None
    # Second call with the same id is a hard error, not a silent
    # reuse (we don't want two agents to race into the same tree).
    wt2, err2 = create_worktree(repo, home, "aaaa1111zzzz")
    assert wt2 is None
    assert err2 and "already exists" in err2


def test_apply_diff_stages_changes(tmp_path):
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, _ = create_worktree(repo, home, "aaaabbbbcccc")
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+goodbye\n"
    )
    ok, err = apply_diff(wt, diff)
    assert ok, err
    # Working tree reflects the patch, and the change is staged.
    assert (wt / "README.md").read_text() == "goodbye\n"
    r = subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--name-only"],
                       capture_output=True, text=True, timeout=10)
    assert r.stdout.strip() == "README.md"


def test_apply_diff_rejects_bad_patch(tmp_path):
    """A patch that doesn't apply cleanly returns (False, err)
    without touching the worktree. Regression guard: agents may
    submit patches against a stale base."""
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, _ = create_worktree(repo, home, "cafe1234beef")
    bad = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n+++ b/README.md\n"
        "@@ -1 +1 @@\n-not-what-is-there\n+something\n"
    )
    ok, err = apply_diff(wt, bad)
    assert not ok
    assert err  # non-empty stderr from git
    # README.md unchanged on disk.
    assert (wt / "README.md").read_text() == "hello\n"


def test_commit_proposal_records_message_and_id(tmp_path):
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, _ = create_worktree(repo, home, "beef1234cafe")
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n+++ b/README.md\n"
        "@@ -1 +1 @@\n-hello\n+world\n"
    )
    assert apply_diff(wt, diff)[0]
    ok, err = commit_proposal(wt, "test title", "test rationale",
                              "beef1234cafedead")
    assert ok, err
    # Commit message includes the request id so a reviewer can
    # trace back to the audit log.
    r = subprocess.run(
        ["git", "-C", str(wt), "log", "-1", "--pretty=%B"],
        capture_output=True, text=True, timeout=10,
    )
    assert "test title" in r.stdout
    assert "test rationale" in r.stdout
    assert "beef1234cafedead" in r.stdout


def test_cleanup_worktree_removes_tree_and_is_idempotent(tmp_path):
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    wt, _ = create_worktree(repo, home, "cccc1234")
    assert wt.exists()
    cleanup_worktree(repo, home, "cccc1234")
    assert not wt.exists()
    # Second call is a no-op (no exception).
    cleanup_worktree(repo, home, "cccc1234")


def test_apply_failure_never_touches_master_ref(tmp_path):
    """Belt-and-braces: even if apply fails INSIDE the worktree
    the main checkout's HEAD is untouched."""
    repo = _init_temp_repo(tmp_path)
    home = tmp_path / "bridge_home"
    master_before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "master"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    wt, _ = create_worktree(repo, home, "eeee5678")
    apply_diff(wt, "not-a-valid-diff\n")   # bound to fail
    cleanup_worktree(repo, home, "eeee5678")
    master_after = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "master"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    assert master_before == master_after


def test_branch_name_uses_short_id_prefix(tmp_path):
    """proposal/<short> keeps branch names readable in ``git
    branch`` listings even with dozens of proposals."""
    from arena.admin.proposal import _branch_name
    assert _branch_name("deadbeef1234abcd") == "proposal/deadbeef"
    assert _branch_name("aaaaBBBBccccDDDD").startswith("proposal/")


# ---------------------------------------------------------------------------
# v4.20.0 regression guards -- both bugs found in v4.19.0 live smoke
# ---------------------------------------------------------------------------

def test_worktree_root_does_not_double_the_arena_proposals(tmp_path):
    """v4.19.0 shipped with a double-.arena_proposals bug:
    handlers_proposal passed ``bridge_home/.arena_proposals`` as
    ``proposal_home`` and ``_worktree_root`` re-appended
    ``.arena_proposals`` inside, so worktrees materialised at
    ``<home>/.arena_proposals/.arena_proposals/worktrees/...``
    instead of ``<home>/.arena_proposals/worktrees/...``.

    v4.20.0 fix: ``_worktree_root`` takes an already-computed
    proposal_home and just appends ``worktrees/<short>``. This
    guard fails immediately if a future edit re-introduces the
    double suffix."""
    from arena.admin.proposal import _worktree_root
    proposal_home = tmp_path / ".arena_proposals"
    wt = _worktree_root(proposal_home, "deadbeef1234")
    # Path must be exactly two segments below proposal_home:
    # <proposal_home>/worktrees/<short>. No extra '.arena_proposals'
    # segment anywhere in the tail.
    assert wt == proposal_home / "worktrees" / "deadbeef"
    parts = wt.relative_to(tmp_path).parts
    assert parts.count(".arena_proposals") == 1, (
        f"double-.arena_proposals regression: {wt}"
    )


def test_create_worktree_end_to_end_lands_at_single_arena_proposals(tmp_path):
    """End-to-end: submit-time helper passes
    ``proposal_home`` (already ending in ``.arena_proposals``),
    ``create_worktree`` must land the branch at exactly
    ``<home>/.arena_proposals/worktrees/<short>/`` -- no doubled
    segment."""
    repo = _init_temp_repo(tmp_path)
    proposal_home = tmp_path / "bridge_home" / ".arena_proposals"
    wt, err = create_worktree(repo, proposal_home, "cafedeadbabe")
    assert err is None, err
    # No doubled segment.
    assert str(wt).count(".arena_proposals") == 1
    assert wt.name == "cafedead"
    assert wt.parent.name == "worktrees"
    assert wt.parent.parent.name == ".arena_proposals"


def test_pick_pytest_python_prefers_interpreter_with_pytest(monkeypatch):
    """v4.19.0 hard-coded ``sys.executable``. On a bridge running
    under a uv-managed Python (PEP 668 externally-managed) pytest
    is often absent from sys.executable but available from
    ``python3`` on PATH. v4.20.0 fix picks the first interpreter
    in ``[python3, /usr/bin/python3, sys.executable]`` that has
    pytest importable.

    We monkey-patch subprocess.run so the test doesn't actually
    invoke any interpreter -- just proves the candidate order and
    the "first success wins" logic."""
    from arena.admin import handlers_proposal as mod

    calls = []

    def _fake_run(argv, **_kw):
        calls.append(argv[0])
        # Only /usr/bin/python3 succeeds; python3 (first) fails.
        rc = 0 if argv[0] == "/usr/bin/python3" else 1
        class _R:
            returncode = rc
        return _R()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    picked = mod._pick_pytest_python()
    assert picked == "/usr/bin/python3"
    # First try must be plain "python3" (PATH lookup), second is
    # the absolute /usr/bin/python3, sys.executable is last.
    assert calls[0] == "python3"
    assert calls[1] == "/usr/bin/python3"


def test_pick_pytest_python_falls_back_when_no_candidate_has_pytest(monkeypatch):
    """If no interpreter has pytest we still return SOMETHING
    (sys.executable) so ``_run_tests_in_worktree`` can invoke it
    and produce a clear ModuleNotFoundError in the tests_tail.
    Silent success would hide the real problem."""
    import sys as _sys
    from arena.admin import handlers_proposal as mod

    class _R:
        returncode = 1

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _R())
    picked = mod._pick_pytest_python()
    assert picked == (_sys.executable or "python3")
