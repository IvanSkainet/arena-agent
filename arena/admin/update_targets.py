"""What an update copies onto the install root, and what it must not touch.

Split out of `auto_update.py` for two reasons, one of them load-bearing:

* That module is at the 600-line runtime cap, and this grew it past it.
* `auto_update_windows.py` needs the same list. Importing it back from
  `auto_update.py` is a circular dependency (auto_update imports the
  Windows helper at its own bottom), and the previous fix -- a lazy
  import inside the function -- silently removed the very cycle that
  `tests/test_e402_deliberate.py` exists to document. A third module
  both platforms import is the honest shape.

The history this encodes: the list of directories to copy was
hand-maintained, and a hand-maintained list of what to ship is a list
that quietly stops shipping things. `chat_extension_firefox` shipped
inside the v4.169.0 release zip and reached nobody. Measured on the
operator's Windows machine after a clean update:

    chat_extension          18 files
    chat_extension_firefox  MISSING

`chat_extension` was missing from the list too, so the browser
extension had never been updated by auto-update at all -- only by a
fresh install. His report was "I can't install the extension, the files
aren't there", and he was describing a bug.
"""
from __future__ import annotations

from pathlib import Path

# Files/directories REPLACED wholesale on install. Everything else in
# the install root is left untouched (config, tokens, logs, state).
_STATIC_REPLACE_TARGETS = (
    "arena",
    "dashboard",
    "docs",
    "scripts",
    "bin",
    "unified_bridge.py",
    "pyproject.toml",
    "README.md",
    "README.ru.md",
    "CHANGELOG.md",
    "CHANGELOG.ru.md",
    "assets",
    "install.sh",
    "install.bat",
    "uninstall.sh",
    "uninstall.bat",
)

# Directories in the install root that belong to the OPERATOR, not to
# the release: config, state, logs, anything they created. These are
# never replaced, and the discovery below skips them.
#
# Deliberately a deny-list rather than an allow-list, which is the whole
# point of the change: a new *product* directory should ship
# automatically, while a new *state* directory is a rare, deliberate
# act that the person adding it will know to list here.
_NEVER_REPLACE = frozenset({
    # Runtime state.
    "queue", "memory", "logs", "missions", "reports", "backups",
    "update", "workspace", "sessions", "profiles", "tmp",
    # Directories that ship with the release BUT accumulate the
    # operator's own work alongside it. Windows copies with
    # `robocopy /MIR`, which deletes anything at the destination that is
    # not in the source -- so replacing these wholesale would delete a
    # skill or project the operator wrote. Losing their work to an
    # update is far worse than shipping a stale bundled example.
    "skills", "projects", "subagents", "hooks", "mcp",
    # Never ours to touch.
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".installer-backup", ".arena",
})


# A directory belongs to the release only if the release *itself* says
# so. The marker is the release manifest written by make_release_zip.py;
# when it is absent (older payload) we fall back to comparing against
# the payload, never against the install root.
RELEASE_MANIFEST = ".arena-release-manifest.json"


def replace_targets(payload_root: "Path | None" = None) -> tuple[str, ...]:
    """What to copy from the payload onto the install root.

    v4.169.2 -- this reads the PAYLOAD and only the payload.

    The first version compared directory names against a deny-list of
    operator state. That is a blacklist, and the thing being enumerated
    is the half that keeps growing: measured on the operator's machine,
    the install root contained `relay`, `code-sessions`, `code-runs`,
    `flight-records`, `autonomy`, `autopilot`, `ship-chain`, `out`,
    `runtime`, `tools`, `mcp-ext`, `mcp-servers` -- twelve runtime
    directories created since the deny-list was written, every one of
    which would have been handed to `robocopy /MIR` and deleted,
    because `/MIR` removes whatever the source does not have.

    The correct question is not "is this operator state?" but "did this
    arrive in the release?". Only the payload can answer that, and it
    answers it by existing: a directory in the freshly unpacked release
    is release content by definition.

    So the deny-list is now a small safety net rather than the
    mechanism, and the mechanism is: enumerate the payload.
    """
    if payload_root is None:
        return _STATIC_REPLACE_TARGETS
    root = Path(payload_root)
    try:
        entries = list(root.iterdir())
    except OSError:
        return _STATIC_REPLACE_TARGETS

    # Refuse to treat an install root as a payload, because handing an
    # install root to `robocopy /MIR` deletes everything the release
    # does not contain.
    #
    # The markers must be things a RELEASE never ships. `queue/` and
    # `memory/` were the obvious guess and both are wrong -- the release
    # ships them with a .gitkeep and an empty facts.db, so keying on
    # them made every real payload look like an install root and the fix
    # silently did nothing. Verified against the actual v4.169.1 zip
    # rather than assumed.
    #
    # A token and an audit log, by contrast, are created at runtime and
    # are explicitly excluded by make_release_zip.py.
    looks_like_install = any(
        (root / marker).exists()
        for marker in ("token.txt", "audit.jsonl", "requests.jsonl",
                       "bridge.log", ".arena-update-apply.log")
    )
    if looks_like_install:
        return _STATIC_REPLACE_TARGETS

    discovered = sorted(
        entry.name for entry in entries
        if entry.is_dir()
        and not entry.name.startswith(".")
        and entry.name not in _NEVER_REPLACE
    )

    seen: list[str] = list(_STATIC_REPLACE_TARGETS)
    for name in discovered:
        if name not in seen:
            seen.append(name)
    return tuple(seen)


# Kept as a module-level name: the Windows mover imports it, and tests
# assert on it. It is the static list; callers that have a payload on
# hand should use `replace_targets(payload_root)`.
_REPLACE_TARGETS = _STATIC_REPLACE_TARGETS
