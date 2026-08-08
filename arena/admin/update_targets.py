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


def replace_targets(payload_root: "Path | None" = None) -> tuple[str, ...]:
    """What to copy from the payload onto the install root.

    The static list above, plus every top-level directory the release
    actually contains that is not operator state. That second half is
    the fix: `chat_extension_firefox` arrived in v4.169.0 and reached
    nobody, because shipping a directory required remembering to name it
    in two places (here and, transitively, the Windows mover).

    Falls back to the static list when the payload cannot be inspected,
    so a bad path degrades to the old behaviour instead of copying
    nothing.
    """
    if payload_root is None:
        return _STATIC_REPLACE_TARGETS
    try:
        discovered = sorted(
            entry.name for entry in Path(payload_root).iterdir()
            if entry.is_dir()
            and not entry.name.startswith(".")
            and entry.name not in _NEVER_REPLACE
        )
    except OSError:
        return _STATIC_REPLACE_TARGETS

    seen = list(_STATIC_REPLACE_TARGETS)
    for name in discovered:
        if name not in seen:
            seen.append(name)
    return tuple(seen)


# Kept as a module-level name: the Windows mover imports it, and tests
# assert on it. It is the static list; callers that have a payload on
# hand should use `replace_targets(payload_root)`.
_REPLACE_TARGETS = _STATIC_REPLACE_TARGETS
