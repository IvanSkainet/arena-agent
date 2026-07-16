"""Agent-driven change proposals (v4.19.0).

Lets an agent submit a patch against the bridge repo, have it
applied to a branch, tested, and (on success) pushed for human
review -- all without direct write-access to the master branch
or to sensitive config files.

Design goals (borrowed from arena.admin.auto_update):

* **Never touches master.** Every proposal lives on a branch
  named ``proposal/<short-request-id>``. Master is untouched.
* **Never touches config / secrets.** A pre-flight patch filter
  rejects diffs that mention token.txt, authtoken.secret, .env,
  .git/config, or any dotfile ending in .secret. The blocklist
  is a set of substring markers; we're deliberately paranoid
  (a false-positive is a rejected proposal, not a leaked token).
* **Tested in an isolated worktree.** We create a fresh
  ``git worktree`` per proposal so the running bridge's checkout
  never has an unmerged patch on disk. Rollback = just remove
  the worktree.
* **No auto-merge.** Successful proposals push their branch and
  return the URL. Merging is a human action.
* **No network at import time.** Everything is lazy so unit
  tests can drive the state machine without ``git`` or a repo.
* **Runs subprocess directly, not through ``run_shell_command``.**
  We don't want proposal apply to show up in ``/v1/ps`` alongside
  agent-invoked commands, and we don't want the exec blocklist
  to interfere with our own git plumbing.

State machine::

    queued  -> applying -> testing -> passed | failed | rejected
                    v
                rejected  (pre-flight filter caught something)

``rejected`` is terminal and means the proposal was refused
without ever touching git; ``failed`` means we applied the patch
but tests didn't pass; ``passed`` means push succeeded.

Storage: JSONL append-only under
``<home>/.arena_proposals/proposals.jsonl``. One line per state
transition -- easy to tail with ``jq`` and easy to prove-correct
against concurrent access (append is atomic on POSIX). The
"current state" of a proposal is the last-line-with-matching-id.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Constants & pre-flight filter
# ---------------------------------------------------------------------------

# Any diff whose content contains one of these substrings is
# refused pre-emptively. The set is deliberately broad -- a
# false positive is a rejected proposal (agent tries again), a
# false negative is a leaked token / master-branch write.
_BLOCKED_PATH_PATTERNS: tuple[str, ...] = (
    "token.txt",
    "authtoken.secret",
    ".env",
    ".git/config",
    ".git/credentials",
    ".git-credentials",
    ".netrc",
    "arena/constants.py",   # VERSION lives here; auto-update owns bumps
    "pyproject.toml",       # same reason
    "audit.jsonl",
    ".ssh/",
    ".aws/credentials",
    ".gnupg/",
)

# Any diff line whose header line matches this regex is refused.
# Catches ``diff --git a/token.txt b/token.txt`` style headers
# and the ``+++ b/foo.env`` / ``--- a/foo.env`` variants git
# emits. Compiled once at import time.
_DIFF_HEADER_RE = re.compile(
    r"^(?:diff --git|---|\+\+\+)\s+.*(?:"
    + "|".join(re.escape(p) for p in _BLOCKED_PATH_PATTERNS)
    + r")",
    re.MULTILINE,
)

# Branch prefix -- every proposal branch starts with this so
# a stray "git push origin master" from the apply path is a
# no-op (nothing on master).
BRANCH_PREFIX = "proposal/"

# Size caps -- refuse anything obviously too large.
_MAX_DIFF_BYTES = 512 * 1024   # 512 KiB of patch text
_MAX_TITLE_LEN = 200
_MAX_RATIONALE_LEN = 4000


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

STATE_QUEUED    = "queued"
STATE_APPLYING  = "applying"
STATE_TESTING   = "testing"
STATE_PASSED    = "passed"
STATE_FAILED    = "failed"
STATE_REJECTED  = "rejected"

_TERMINAL_STATES = {STATE_PASSED, STATE_FAILED, STATE_REJECTED}


@dataclass
class Proposal:
    """One agent-submitted change proposal.

    Populated at ``submit()`` time and mutated in-place as the
    state machine advances. The dict-shape returned from
    ``as_public_dict()`` is what agents actually see -- it hides
    the raw diff body (too large to echo everywhere) and exposes
    a diff SHA-256 fingerprint instead.
    """
    request_id: str
    title: str
    rationale: str
    diff_bytes: int
    diff_sha256: str
    branch: str
    state: str = STATE_QUEUED
    reason: str | None = None
    submitted_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    exit_code: int | None = None
    tests_tail: str | None = None
    push_url: str | None = None
    client: str | None = None

    def as_public_dict(self) -> dict[str, Any]:
        """Redacted shape for /v1/admin/proposal/status responses."""
        d = asdict(self)
        # Timestamps as ISO for readability.
        d["submitted_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.submitted_at))
        d["updated_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.updated_at))
        return d


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------

def validate_diff(diff: str) -> tuple[bool, str | None]:
    """Return ``(ok, reason_or_none)``. Called BEFORE any git
    activity so a rejected proposal never touches the working
    tree. Cheapest possible check: size cap first, then
    blocklist substring scan, then header regex."""
    if not diff or not diff.strip():
        return False, "empty diff"
    if len(diff.encode("utf-8", "replace")) > _MAX_DIFF_BYTES:
        return False, (
            f"diff too large ({len(diff)} chars); cap is "
            f"{_MAX_DIFF_BYTES} bytes"
        )
    # Substring pre-scan. Catches obvious markers even if the diff
    # is not well-formed git output (e.g. `token.txt` mentioned in
    # a comment inside a patched Python file). Deliberately paranoid.
    lower = diff.lower()
    for pat in _BLOCKED_PATH_PATTERNS:
        if pat.lower() in lower:
            return False, f"diff mentions blocked path pattern: {pat!r}"
    # Header regex. A well-formed diff that renamed AROUND a
    # blocked path would slip past the substring scan only if the
    # regex isn't broad enough -- guard here too.
    m = _DIFF_HEADER_RE.search(diff)
    if m:
        return False, (
            f"diff header targets a blocked path: {m.group(0).strip()!r}"
        )
    return True, None


def validate_metadata(title: str, rationale: str) -> tuple[bool, str | None]:
    """Refuse obviously bad submissions. Every proposal must
    have a title and a rationale -- otherwise reviewing the
    branch is guesswork."""
    if not title or not title.strip():
        return False, "empty title"
    if len(title) > _MAX_TITLE_LEN:
        return False, f"title too long ({len(title)}); cap {_MAX_TITLE_LEN}"
    if not rationale or not rationale.strip():
        return False, "empty rationale"
    if len(rationale) > _MAX_RATIONALE_LEN:
        return False, (
            f"rationale too long ({len(rationale)}); cap "
            f"{_MAX_RATIONALE_LEN}"
        )
    return True, None


# ---------------------------------------------------------------------------
# JSONL store -- append-only, one line per state transition
# ---------------------------------------------------------------------------

class ProposalStore:
    """Tiny append-only ledger. ``append(p)`` writes one JSON
    line with ``p.as_public_dict() + {"diff_kept": False}``; the
    raw diff is NEVER persisted here (it lives in the branch,
    which is the ground truth).

    Reading is O(n) over the file -- fine for the expected
    volume (dozens of proposals at most). If it ever gets large
    we'll add a SQLite backend behind the same interface.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, p: Proposal) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(p.as_public_dict(), ensure_ascii=False))
            fh.write("\n")

    def load_latest(self, request_id: str) -> dict[str, Any] | None:
        """Return the latest recorded state for ``request_id``,
        or None if we've never seen it. Scans the file top-down
        keeping the last-matching record (append-only ledger)."""
        if not self.path.exists():
            return None
        latest = None
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("request_id") == request_id:
                    latest = rec
        return latest

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the last ``limit`` distinct proposals (by
        request_id), newest-first. Handy for a dashboard."""
        if not self.path.exists():
            return []
        by_id: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rid = rec.get("request_id")
                if not rid:
                    continue
                if rid not in by_id:
                    order.append(rid)
                by_id[rid] = rec   # keep latest
        # Reverse for newest-first.
        out = [by_id[rid] for rid in reversed(order)]
        return out[:max(1, min(limit, 200))]


# ---------------------------------------------------------------------------
# Git plumbing (isolated worktree)
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str, timeout: int = 60,
         input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """Thin wrapper around ``git`` that always returns the
    CompletedProcess (we inspect returncode). Never raises for
    non-zero exits -- caller decides."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, timeout=timeout, input=input_bytes,
    )


def _worktree_root(bridge_home: Path, request_id: str) -> Path:
    """Where we materialise the proposal branch's working copy.
    Kept OUTSIDE the main checkout so the running bridge's
    files never fight the apply."""
    return bridge_home / ".arena_proposals" / "worktrees" / request_id[:8]


def _branch_name(request_id: str) -> str:
    return f"{BRANCH_PREFIX}{request_id[:8]}"


def create_worktree(repo: Path, bridge_home: Path,
                    request_id: str, base_ref: str = "HEAD"
                    ) -> tuple[Path | None, str | None]:
    """Materialise a fresh worktree at
    ``<home>/.arena_proposals/worktrees/<short>/`` on a new
    branch ``proposal/<short>``. Returns ``(worktree_path, None)``
    on success or ``(None, error_reason)`` on failure."""
    wt = _worktree_root(bridge_home, request_id)
    if wt.exists():
        return None, f"worktree already exists at {wt}"
    branch = _branch_name(request_id)
    wt.parent.mkdir(parents=True, exist_ok=True)
    r = _git(repo, "worktree", "add", "-b", branch, str(wt), base_ref)
    if r.returncode != 0:
        return None, (
            r.stderr.decode("utf-8", "replace").strip()
            or f"git worktree add exit={r.returncode}"
        )
    return wt, None


def apply_diff(worktree: Path, diff: str) -> tuple[bool, str | None]:
    """``git apply`` the patch inside the worktree. Uses
    ``--index`` so the changes are staged (ready to commit)
    but returns before committing so the caller can decide
    whether to proceed."""
    diff_bytes = diff.encode("utf-8", "replace")
    r = _git(worktree, "apply", "--index", "--whitespace=nowarn", "-",
             input_bytes=diff_bytes, timeout=30)
    if r.returncode != 0:
        return False, (
            r.stderr.decode("utf-8", "replace").strip()
            or f"git apply exit={r.returncode}"
        )
    return True, None


def commit_proposal(worktree: Path, title: str,
                    rationale: str, request_id: str
                    ) -> tuple[bool, str | None]:
    """Commit the staged changes with a message combining title
    and rationale. Uses ``-c`` overrides so we don't need the
    bridge's git identity to be configured."""
    msg = (
        f"proposal: {title}\n\n"
        f"{rationale}\n\n"
        f"agent-request-id: {request_id}\n"
    )
    r = subprocess.run(
        ["git", "-C", str(worktree),
         "-c", "user.name=arena-agent-proposal",
         "-c", "user.email=proposal@arena.ai",
         "commit", "-m", msg],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        return False, (
            r.stderr.decode("utf-8", "replace").strip()
            or f"git commit exit={r.returncode}"
        )
    return True, None


def cleanup_worktree(repo: Path, bridge_home: Path,
                     request_id: str) -> None:
    """Best-effort remove of the worktree. Never raises --
    called from finally blocks. If the worktree is dirty
    (patch application failed mid-way) ``git worktree remove
    --force`` gets rid of it."""
    wt = _worktree_root(bridge_home, request_id)
    if not wt.exists():
        return
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
        capture_output=True, timeout=30,
    )
    # Belt and braces: rm -rf the dir if the worktree remove
    # didn't cover it (rare, but happens if the branch was
    # already deleted).
    if wt.exists():
        import shutil
        shutil.rmtree(wt, ignore_errors=True)


__all__ = [
    "BRANCH_PREFIX",
    "Proposal",
    "ProposalStore",
    "STATE_QUEUED", "STATE_APPLYING", "STATE_TESTING",
    "STATE_PASSED", "STATE_FAILED", "STATE_REJECTED",
    "validate_diff",
    "validate_metadata",
    "create_worktree",
    "apply_diff",
    "commit_proposal",
    "cleanup_worktree",
]
