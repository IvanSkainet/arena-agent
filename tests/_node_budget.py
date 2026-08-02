"""One budget for every `node -e` call in the suite.

Five test modules each hardcoded their own subprocess timeout for Node (10 s
or 15 s, by copy-paste). Those numbers were sized on a warm Linux runner. On a
cold, contended windows-latest agent, Node's first start pays for process
creation, Defender inspection and a multi-kilobyte script on stdin -- and the
10 s modules went red twice, looking like flakes both times.

The fix is not a bigger magic number in five places; it is one number in one
place, overridable per host, with a gate (`tests/test_node_budget.py`) that
fails if a module drifts back to its own literal.

Green here proves nothing about Node's behaviour -- only that the suite cannot
silently re-acquire five inconsistent budgets.
"""
from __future__ import annotations

import os
import platform

#: Seconds allowed for a single `node -e` invocation.
#:
#: Windows agents are the slow case by a wide margin, so they get the larger
#: allowance rather than every platform paying for the worst one.
NODE_TIMEOUT_S: int = 60 if platform.system().lower() == "windows" else 30


def node_timeout() -> int:
    """Budget for one Node invocation, honouring ``ARENA_TEST_NODE_TIMEOUT``.

    The env override exists for genuinely slow hosts; it can only raise the
    budget, never lower it below the platform default, because a too-small
    budget is precisely the failure this module was written to remove.
    """
    raw = os.environ.get("ARENA_TEST_NODE_TIMEOUT", "").strip()
    if not raw:
        return NODE_TIMEOUT_S
    try:
        return max(NODE_TIMEOUT_S, int(raw))
    except ValueError:
        return NODE_TIMEOUT_S


__all__ = ["NODE_TIMEOUT_S", "node_timeout"]
