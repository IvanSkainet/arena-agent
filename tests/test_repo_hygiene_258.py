"""Two checks that no other gate in this repository performs.

Why these two, and why here
---------------------------
Item 4 of #258 asked whether to adopt pre-commit.ci. The answer was no: the
service runs hooks in its own environment, so the four `language: system`
hooks in `.pre-commit-config.yaml` -- the ruff and ratchet hooks, the ones
that carry signal -- cannot run there at all and would have to be listed in
`ci: skip:`. A green check reporting that five trivial hooks passed, while
the four that matter are skipped by configuration, is the green-checkmark
fallacy AGENTS.md is about.

But two of those five hooks check something genuinely uncovered here:

  * `check-added-large-files` -- nothing in CI looks at blob size. Git keeps
    every version of a large file forever; noticing a 40 MB artifact after
    it is three commits deep means rewriting history, and by then it has
    been fetched by everyone who cloned.

  * `check-merge-conflict` -- nothing looks for conflict markers either.
    A marker left in a Python file is caught by the syntax error that
    follows, but one in Markdown, JSON-with-comments, or a workflow's
    free-text field lands silently.

Twenty lines here replace an external service, a `ci: skip:` list, and a bot
with write access to pull request branches. They live in `tests/` rather
than as a workflow step so they run inside the Tests matrix, which is
already required, instead of adding another optional check nobody has to
look at.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tests._git_budget import git_timeout  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The threshold `.pre-commit-config.yaml` already uses, kept identical so the
# local hook and this gate cannot disagree about what "too large" means.
MAX_KB = 2048

# Written split so this file does not trip the very check it implements: a
# literal marker here would be found by the scan below (and by anyone's
# editor). `<<<` and `>>>` are the git default conflict style; `|||` appears
# only with diff3/zdiff3, which is worth catching for the same reason.
CONFLICT_PREFIXES = ("<" * 7 + " ", ">" * 7 + " ", "|" * 7 + " ")

# Binary and vendored paths where a "line" is meaningless. Kept deliberately
# short: an exclusion list is the usual way a check like this rots into
# passing on everything.
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
                 ".gz", ".whl", ".jar", ".apk", ".keystore", ".woff",
                 ".woff2", ".ttf", ".mp3", ".wav", ".onnx", ".bin")


def _tracked_files() -> list[pathlib.Path]:
    """Files git actually tracks, which is what ends up in a clone.

    Not `Path.rglob`: that would walk build outputs, virtualenvs and caches
    that are ignored and never shipped, and every one of them would be a
    false positive with a plausible-looking path.
    """
    # The shared budget from tests/_git_budget.py, not a literal. Windows
    # runners are slow enough at process creation that hand-picked numbers
    # flaked here before (#145), and `tests/test_git_budget.py` enforces
    # that every git call in the suite uses the one budget.
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, check=True, timeout=git_timeout(),
    )
    # Decoded explicitly as UTF-8, not via `text=True`. That would use
    # locale.getpreferredencoding(), which is cp1252 on the Windows machine
    # this suite also runs on: a tracked filename with non-ASCII bytes would
    # decode into a garbled string, `is_file()` would return False, and the
    # file would drop out of both gates below with no error and no failure.
    # git emits pathnames as raw UTF-8 under `-z`.
    paths = [
        REPO_ROOT / name
        for name in result.stdout.decode("utf-8").split("\0")
        if name
    ]

    # Fail loudly rather than filtering, and require a real readable file:
    # `is_file()` follows symlinks, so a dangling link fails here too. A
    # tracked path that does not resolve is a broken symlink or a decoding
    # problem, and both are reasons to look. Returning the filtered list
    # instead is how a fail-closed check turns into one that passes on less
    # and less: the entry disappears and the gates below scan one file
    # fewer, with no error and no failure.
    unreadable = [str(path) for path in paths if not path.is_file()]
    assert not unreadable, (
        "git tracks paths that do not resolve to a file here "
        f"(broken symlink, or a name this checkout could not create): {unreadable}"
    )
    return paths


def _first_marker(path: pathlib.Path) -> str | None:
    """`path:line` of the first conflict marker, or None.

    Lifted out of the test so the loop over files stays flat: the guard, the
    decode, the line walk and the prefix test are four levels in one
    function otherwise, which is what CodeScene flags as a bumpy road.
    """
    if path.suffix.lower() in SKIP_SUFFIXES:
        return None
    # No `try`/`except OSError` here. Every path is a readable file by the
    # time it arrives (`_tracked_files` asserts that), so a read that fails
    # now is a permission problem or a race, not a file to skip. Swallowing
    # it would put this function back to passing on whatever it could not
    # open -- the same silent drop the assert above exists to prevent.
    raw = path.read_bytes()
    # errors="replace", not a UTF-8 decode that gives up. A latin-1 or
    # cp1252 .md is a real text file, conflict markers are pure ASCII, and
    # bailing out on the decode would skip exactly the silent-commit case
    # this test exists to catch. Undecodable bytes become U+FFFD, which
    # cannot start a line with a marker prefix.
    text = raw.decode("utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(CONFLICT_PREFIXES):
            return f"{path.relative_to(REPO_ROOT)}:{number}"
    return None


def test_no_tracked_file_is_oversized() -> None:
    """Nothing in CI looks at blob size, and git never forgets one."""
    oversized = [
        f"{path.relative_to(REPO_ROOT)} ({path.stat().st_size // 1024} KiB)"
        for path in _tracked_files()
        if path.stat().st_size > MAX_KB * 1024
    ]
    assert not oversized, (
        f"tracked files over {MAX_KB} KiB: {oversized}. Git stores every "
        "version of these forever -- removing one later means rewriting "
        "history that other clones already have. If a large file genuinely "
        "belongs in the repository, raise MAX_KB here and in "
        ".pre-commit-config.yaml together, and say in the commit why."
    )


def test_no_tracked_file_carries_a_conflict_marker() -> None:
    """A marker in a non-Python file lands without any syntax error to catch it."""
    offenders = [
        found
        for path in _tracked_files()
        if (found := _first_marker(path)) is not None
    ]
    assert not offenders, (
        f"conflict markers left in tracked files: {offenders}. In Python "
        "these produce a syntax error, but in Markdown, JSON or a workflow's "
        "free-text fields they are committed silently."
    )
