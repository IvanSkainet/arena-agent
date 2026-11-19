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
    where state lives: an explicit ``ARENA_AGENT_HOME`` or ``~/arena-bridge``
    for fresh installs. Existing checkout state retains its legacy location
    until the operator explicitly chooses/migrates it; never silently choose
    between two nonempty stores. This is distinct from the workspace.
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

import hashlib
import os
from functools import lru_cache
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
    return _compatible_default()



def default_home() -> Path:
    """Historical user-home location, also searched for legacy configuration."""
    return Path.home() / DATA_DIRNAME


# Fixed fingerprints distinguish shipped examples from operator state.
_SHIPPED_CONFIGURATION = {'mcp/mcp.json': 'ad92b392fedcaaed1f104384c734092dcf8b5ca56a3ee260916901de2d3e65cd',
 'mcp/registry.json': '57f930b7ef66e51782f3c903d62f4cfa72a7d47f5671badf444d2bf3a90fa5a1',
 'webhooks.json': '2119d4d751fb0d7b873d49a5e40e2b6f895eb1e83f90889d7483a3f45e707dd1'}


def _state_file(root: Path, relative: str) -> bool:
    path = root / relative
    try:
        if path.is_symlink():
            return True
        if not path.is_file():
            return False
        digest = _SHIPPED_CONFIGURATION.get(relative)
        return digest is None or hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != digest
    except OSError:
        return True  # unreadable state must never be silently abandoned


def _has_state(root: Path) -> bool:
    fixed = ("memory/facts.db", "memory/facts.jsonl", "audit.jsonl", "capability-gaps.json",
             *_SHIPPED_CONFIGURATION)
    if any(_state_file(root, name) for name in fixed):
        return True
    patterns = ("queue/*/*.json", "missions/*.json", "missions/*/mission.json", "relay/**/*.json",
                "code-runs/*", "mcp-servers/*")
    return any(any(root.glob(pattern)) for pattern in patterns)


def _compatible_default() -> Path:
    """Keep pre-upgrade state reachable; never silently pick between two stores.

    Empty source-template directories are not state. An explicit environment
    setting always bypasses this compatibility lookup. No bytes are moved or
    deleted; an operator can migrate at a controlled maintenance boundary.
    """
    return _choose_default(default_home(), code_root())


@lru_cache(maxsize=16)
def _choose_default(primary: Path, legacy: Path) -> Path:
    """Pin the compatibility choice for each root pair for this process.

    New files appearing later must not move a live process to another store.
    Environment and explicit overrides remain dynamic, outside this cache.
    """
    if primary.resolve() == legacy.resolve() or not _has_state(legacy):
        return primary
    if _has_state(primary):
        raise RuntimeError("state exists in both the code directory and user home; "
                           "set ARENA_AGENT_HOME explicitly before starting")
    return legacy


def code_root() -> Path:
    """The directory the code lives in — the parent of the ``arena`` package."""
    return Path(__file__).resolve().parent.parent


def executable_root() -> Path:
    """Compatibility tools live in the checkout or wheel-owned resource tree."""
    source = code_root()
    if (source / "bin" / "agentctl").is_file():
        return source
    return Path(__file__).resolve().parent / "_executables"


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
    primary = _default_token_root() / "token.txt"
    if for_write or primary.exists():
        return primary
    legacy = code_root() / "token.txt"
    return legacy if legacy.exists() else primary


def _default_token_root() -> Path:
    root = agent_home()
    if not os.environ.get("ARENA_AGENT_HOME", "").strip() and root == code_root():
        return default_home()
    return root


def sandbox_home() -> Path:
    """The filesystem tree the agent is allowed to touch, read from the live config.

    Imported lazily: ``arena.runtime_profile`` is published by bridge startup
    and is ``None`` for CLIs and tests, which is exactly when ``$HOME`` is the
    right answer.
    """
    from arena.runtime_profile import current_config

    cfg = current_config()
    if cfg:
        root = cfg.get("root")
        if root:
            return _normalise(root)
    return Path.home()


__all__ = [
    "DATA_DIRNAME",
    "agent_home",
    "code_root",
    "executable_root",
    "sandbox_home",
    "token_path",
]
