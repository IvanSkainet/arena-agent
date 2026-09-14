"""Import a module under a temporary `ARENA_AGENT_HOME`, and undo it.

Several production modules read their configuration **at import**:
`arena/chat_cli/common.py` binds `HOME`, `arena/agent_helpers/files.py`
binds `ROOT`/`FACTS`. A test that needs them pointed at a tmp home has
to set the variable before the `import` statement -- a fixture runs too
late -- and then has to undo three separate things, in the right order.
Getting any of them wrong leaks state into every module collected
afterwards, which is #348.

The block was duplicated almost verbatim in two test modules, so it
lives here instead, next to the reasoning for each step.
"""
from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator


def _evict(module_name: str) -> None:
    """Release every reference that keeps a module's bound constants alive.

    `sys.modules` is the obvious one. The parent package is not: an
    `import a.b` also binds `b` as an attribute of `a`, so
    `from a import b` still finds the stale object -- with its `ROOT`
    still pointing at the tmp home -- after the `sys.modules` entry is
    gone. Verified by mutation: dropping only the `sys.modules` entry
    hands the tmp home to the next importer via that import form.
    """
    sys.modules.pop(module_name, None)
    parent_name, _, attribute = module_name.rpartition(".")
    if not parent_name:
        return
    parent = sys.modules.get(parent_name)
    if parent is not None and getattr(parent, attribute, None) is not None:
        delattr(parent, attribute)


@contextlib.contextmanager
def agent_home(path: str, *evict: str) -> Iterator[None]:
    """Point `ARENA_AGENT_HOME` at `path` for the duration of an import.

    `evict` names the modules whose import-time constants were bound
    from that home. They are released on the way out, so the next
    importer evaluates them against the environment it actually runs
    under -- and on the way in, so a copy cached by an earlier importer
    cannot make the import below a no-op that keeps the earlier home.

    The teardown is in a `finally` because a failing import is exactly
    when it matters: pytest reports the collection error and carries on
    importing later modules, which would otherwise inherit the tmp home
    -- the leak this exists to prevent, via the error path.

    Modules are evicted *before* the variable is restored. Order
    matters wherever eviction can trigger a re-import, since a reload
    that runs after the restore re-reads the wrong value.
    """
    previous = os.environ.get("ARENA_AGENT_HOME")
    os.environ["ARENA_AGENT_HOME"] = path
    # Also evicted on the way *in*. If one of these modules is already
    # cached from an earlier import -- under whatever home was current
    # then -- the import below is a no-op and the constants keep the
    # earlier value, so the test silently runs against the wrong home.
    # Reproduced: with `arena.agent_helpers.files` pre-imported,
    # `runtime.FACTS` pointed at the first module's tmp directory.
    for module_name in evict:
        _evict(module_name)
    try:
        yield
    finally:
        for module_name in evict:
            _evict(module_name)
        if previous is None:
            os.environ.pop("ARENA_AGENT_HOME", None)
        else:
            os.environ["ARENA_AGENT_HOME"] = previous
