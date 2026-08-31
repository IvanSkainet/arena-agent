"""Caller-supplied environment policy for exec endpoints.

Shared by the buffered ``/v1/exec`` handler and the ``/v1/exec/stream``
handler (the raw-script endpoint takes no caller ``env`` payload). The
webview is untrusted input like any other frontend: names that decide
*what actually runs* — interpreter resolution, shell selection, dynamic
loading, module lookup, Git/SSH helper and Node runtime selection — are
never taken from the caller, on POSIX or Windows. Where user data lives (TEMP, APPDATA, USERPROFILE, …) is a
different invariant and deliberately not blocked here.
"""

from __future__ import annotations

from typing import Any

# Exact-match (case-insensitive) denylist. These names choose the binary
# that runs or the code loaded into it — the counterparts of each other
# across platforms (PATH ~ resolution, BASH_ENV/AUTORUN ~ shell startup,
# LD_PRELOAD/APPINIT_DLLS ~ code injection).
_BLOCKED_ENV_EXACT = frozenset({
    # The bridge's own credential: a caller must not be able to override
    # or shadow it for a spawned command.
    "ARENA_TOKEN",
    # POSIX execution control: dynamic loading, shell startup, interpreter
    # and git behavior.
    "PATH", "IFS", "SHELL", "ENV", "BASH_ENV", "ZDOTDIR",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND",
    # Git/SSH/Node helper selection: programs Git, ssh or Node will execute
    # on the caller's behalf during ordinary operations (diff output, askpass,
    # module lookup, runtime option injection) -- GIT_SSH_COMMAND's family.
    "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "SSH_ASKPASS",
    "NODE_PATH", "NODE_OPTIONS",
    # macOS execution control: the DYLD_* family is the counterpart of
    # LD_PRELOAD / LD_LIBRARY_PATH on Darwin.
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    # Windows execution control: interpreter and shell selection, DLL
    # preload, module path, cmd AutoRun.
    "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "APPINIT_DLLS", "PSMODULEPATH", "AUTORUN",
})

# Secret-shaped names stay substring-based: the universe of credential
# variable names is unknowable, so the families are matched broadly and
# the false positives (MONKEY, TOKENIZE) are accepted — dropping a benign
# variable costs a caller nothing, leaking a credential costs everything.
# BASH_FUNC_ covers exported-shell-function injection
# ("BASH_FUNC_foo%%=() {...}"), which is name-prefixed rather than exact.
_BLOCKED_ENV_SUBSTRINGS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "BASH_FUNC_")


def filter_caller_env(env_extra: dict[str, Any]) -> dict[str, str]:
    """Drop env names a caller must not set on a spawned command.

    Everything that survives is stringified; the handlers merge it over
    ``os.environ.copy()`` so the child keeps its base environment.
    """
    kept: dict[str, str] = {}
    for key, value in env_extra.items():
        name = str(key).upper()
        if name in _BLOCKED_ENV_EXACT:
            continue
        if any(pattern in name for pattern in _BLOCKED_ENV_SUBSTRINGS):
            continue
        kept[str(key)] = str(value)
    return kept
