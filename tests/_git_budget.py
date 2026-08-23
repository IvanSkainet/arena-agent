"""One budget for every `git` subprocess in the suite.

Five test modules each hardcoded their own timeout for git, at four different
values -- 5, 10, 15 and 60 seconds -- for the same handful of operations.
`git commit` was allowed 5 s in one module and 10 s in another, decided by
whichever file was copied from.

The 5 s literals were the ones that broke. PR #144 hit this on
windows-latest:

    FAILED tests/test_git_tools.py::test_git_commit_nothing_to_commit
      subprocess.TimeoutExpired: Command '['git', 'commit', '-m',
      'initial commit']' timed out after 5 seconds

Linux and macOS passed; a rerun of the same commit was green. A flake is worse
than a hard failure -- it costs a rerun cycle on an unrelated PR and teaches
people to re-run red CI without reading it.

Why git is slow on windows-latest specifically: process creation is expensive,
Defender inspects every object written into `.git`, and `git commit` fsyncs.
None of that is visible on a warm Linux runner, which is where every one of
these numbers was chosen.

This mirrors `tests/_node_budget.py` exactly, so there is one way to do this in
the codebase rather than two. As there: green here proves nothing about git's
behaviour, only that the suite cannot silently re-acquire four inconsistent
budgets.
"""

from __future__ import annotations

import os
import platform


#: Seconds allowed for a single `git` invocation in tests.
#:
#: Windows agents are the slow case by a wide margin, so they get the larger
#: allowance rather than every platform paying for the worst one. 30 s is six
#: times the literal that actually failed, and still short enough that a truly
#: hung git fails the test rather than the job's wall clock.
def budget_for(system: str) -> int:
    """Budget for a named platform, as `platform.system()` spells it.

    Split out from the module constant so both branches are reachable on any
    OS: the Windows number is the one this change exists for, and it would
    otherwise never be exercised by the Linux and macOS CI jobs.
    """
    return 30 if system.lower() == "windows" else 15


GIT_TIMEOUT_S: int = budget_for(platform.system())


def git_timeout() -> int:
    """Budget for one git invocation, honouring ``ARENA_TEST_GIT_TIMEOUT``.

    The env override exists for genuinely slow hosts; it can only raise the
    budget, never lower it below the platform default, because a too-small
    budget is precisely the failure this module was written to remove.
    """
    raw = os.environ.get("ARENA_TEST_GIT_TIMEOUT", "").strip()
    if not raw:
        return GIT_TIMEOUT_S
    try:
        return max(GIT_TIMEOUT_S, int(raw))
    except ValueError:
        return GIT_TIMEOUT_S


__all__ = ["GIT_TIMEOUT_S", "budget_for", "git_timeout"]
