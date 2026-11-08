"""Where the agent's home is — the one place that answers it.

Three questions used to be answered three different ways, by three
different layers, with three different defaults:

===================  ==========================================  =========================
question             answered where                              default used
===================  ==========================================  =========================
where live the data  ``arena/paths.py``                          **the code directory**
where live the data  ``agentctl_common``, ``missions_cli``, …    ``~/arena-bridge``
which tree is the     ``wiring/observability_registries.py``     ``$HOME``
agent allowed to touch
===================  ==========================================  =========================

The consequences were not cosmetic. A bridge started as
``python unified_bridge.py serve`` wrote missions, queue and relay into the
checkout it was launched from (and, in a pip install, into ``site-packages``),
while ``agentctl`` looked for the same files in ``~/arena-bridge``. A bridge
started with ``--root`` outside ``$HOME`` kept its data in a directory its own
fs endpoints refused to read. And ``agentctl mcp`` looked for its *own script*
in the data directory, which is how it ended up printing an interpreter
traceback about ``~/arena-bridge/bin/mcp_marketplace.py``.

Three distinct notions were being conflated:

``agent_home()``
    where state lives: ``ARENA_AGENT_HOME`` or ``~/arena-bridge``. Never the
    directory the code was installed into, and never the workspace.
``code_root()``
    where the code lives: the directory containing the ``arena`` package. Its
    ``bin/`` holds the scripts the CLI runs, so it must not depend on the data
    directory.
``sandbox_home()``
    which tree the agent may touch: ``serve --root`` when the bridge published
    its config, else ``$HOME``. The data directory is always readable through
    the fs endpoints as well — an agent that cannot read its own queue cannot
    debug its own work.

Nothing here reads a request or a config file: the module is a leaf, so any
layer may import it (see the import-linter contracts in ``pyproject.toml``).
"""
from __future__ import annotations

import os
from pathlib import Path

#: Directory name under ``$HOME`` used when nothing else says otherwise.
DATA_DIRNAME = "arena-bridge"


def _normalise(value: str | Path) -> Path:
    """``expanduser`` once, in one place, so ``~`` means the same everywhere."""
    return Path(value).expanduser()


def agent_home(explicit: str | Path | None = None, *, env_wins: bool = False) -> Path:
    """The directory holding the agent's state.

    Precedence: an explicit value (``--root``-style override, tests) wins, then
    ``ARENA_AGENT_HOME``, then ``~/arena-bridge``. The code directory is never
    a candidate: ``pip install`` must not turn ``site-packages`` into the
    place where queue files appear (#B-006).

    ``env_wins=True`` flips the first two. It exists for one caller,
    ``ArenaPaths.from_env``, whose documented contract is that the environment
    beats the fallback it was handed — the fallback used to be the code
    directory, and an operator's ``ARENA_AGENT_HOME`` has to beat that. Kept as
    a flag rather than a second resolver: the whole point of this module is that
    the question is answered in one place.
    """
    env = os.environ.get("ARENA_AGENT_HOME", "").strip()
    first, second = (env, explicit) if env_wins else (explicit, env)
    for candidate in (first, second):
        if candidate is not None and str(candidate).strip():
            return _normalise(candidate)
    return Path.home() / DATA_DIRNAME


def code_root() -> Path:
    """The directory the code lives in — the parent of the ``arena`` package."""
    return Path(__file__).resolve().parent.parent


def token_path(explicit: str | Path | None = None, *, for_write: bool = False) -> Path:
    """Where the bearer token file is expected.

    Same three sources as :func:`agent_home`, plus ``ARENA_TOKEN_FILE``, which
    already had that meaning in ``agentctl`` and is kept for compatibility.

    The token moved from the checkout (``TOKEN_FILE`` next to
    ``unified_bridge.py``) to ``agent_home()`` after 4.170.0. An installation
    whose token was minted by an older version still has it in the checkout, and
    silently falling back to "no token here, generate a new one" would log out
    every client on upgrade. So for *reads* the old location is honoured while
    it exists; :func:`generate`-style callers pass ``for_write=True`` and always
    get the new location.
    """
    if explicit is not None and str(explicit).strip():
        return _normalise(explicit)
    env_file = os.environ.get("ARENA_TOKEN_FILE", "").strip()
    if env_file:
        return _normalise(env_file)
    primary = agent_home() / "token.txt"
    if for_write or primary.exists():
        return primary
    legacy = code_root() / "token.txt"
    if legacy.exists():
        return legacy
    return primary


def sandbox_home() -> Path:
    """The filesystem tree the agent is allowed to touch, read from the live config.

    Imported lazily: ``arena.runtime_profile`` is published by bridge startup
    and is ``None`` for CLIs and tests, which is exactly when ``$HOME`` is the
    right answer.
    """
    try:
        from arena.runtime_profile import current_config

        cfg = current_config()
    except Exception:  # pragma: no cover - import cycle guard, never expected
        cfg = None
    if cfg:
        root = cfg.get("root")
        if root:
            return _normalise(root)
    return Path.home()


__all__ = [
    "DATA_DIRNAME",
    "agent_home",
    "code_root",
    "sandbox_home",
    "token_path",
]
