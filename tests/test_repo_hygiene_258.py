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
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [
        REPO_ROOT / name
        for name in result.stdout.split("\0")
        if name and (REPO_ROOT / name).is_file()
    ]


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
    offenders = []
    for path in _tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: no lines to inspect
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(CONFLICT_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
                break
    assert not offenders, (
        f"conflict markers left in tracked files: {offenders}. In Python "
        "these produce a syntax error, but in Markdown, JSON or a workflow's "
        "free-text fields they are committed silently."
    )
