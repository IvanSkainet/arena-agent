#!/usr/bin/env python3
"""Fail-closed guard: a dependency held back on purpose must be held back
in the one place a bot reads.

Why this exists
---------------
`requirements-mutation.in` has carried this line since the mutation sweep
was built:

    # mutmut 2.5.1, NOT 3.x: 3.x copies the source tree into mutants/ and
    # breaks this project's imports. Measured, not assumed.

Dependabot proposed `mutmut 3.7.0` anyway, in PR #5, because a comment in
a `.in` file is prose and the bot reads `.github/dependabot.yml`. The
reason was documented, reviewed and useless.

That PR would have merged green. The mutation sweep is
`workflow_dispatch`-only, so no pull-request check runs mutmut; nothing
in the pipeline would have executed the broken version. The breakage
would have surfaced by hand, weeks later, as a sweep that no longer runs
— and by then the bump looks like old, reviewed history.

Verified on 3.7.0 rather than trusted: the 3.x CLI aborts before it
parses arguments (`mutmut --version` raises FileNotFoundError out of
`_guess_source_paths`), so every invocation `scripts/mutation_sweep.py`
makes fails outright.

What is checked
---------------
For every entry in HELD_BACK below:

  1. the pin in the `.in` file still satisfies the constraint — nobody
     bumped it past the ceiling by hand;
  2. `.github/dependabot.yml` carries a matching `ignore` entry, so the
     bot cannot propose the bump in the first place;
  3. the `.in` file still explains WHY in prose a human can read.

Point 2 is the one that matters: it converts a comment into a constraint
the automation obeys. Points 1 and 3 stop the entry from rotting into a
line nobody understands.

Adding a deliberate hold means adding it here, which is the point: the
decision gets recorded once, in a form both a person and a bot respect.

Usage:  python3 scripts/held_back_deps_ratchet.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


class Hold:
    """One dependency deliberately pinned below the latest release."""

    def __init__(
        self,
        name: str,
        declared_in: str,
        max_exclusive: str,
        rationale_keyword: str,
        why: str,
    ) -> None:
        self.name = name
        self.declared_in = declared_in
        # The first version we must NOT take, e.g. "3.0" for "stay on 2.x".
        self.max_exclusive = max_exclusive
        # A word that must survive in the .in prose, so the note cannot
        # decay into "pinned for historical reasons".
        self.rationale_keyword = rationale_keyword
        self.why = why


HELD_BACK = [
    Hold(
        name="mutmut",
        declared_in="requirements-mutation.in",
        max_exclusive="3.0",
        rationale_keyword="mutants",
        why=(
            "3.x copies the source tree into mutants/ and breaks this "
            "project's imports; its CLI aborts before parsing arguments"
        ),
    ),
    Hold(
        name="websockets",
        declared_in="requirements-ci.in",
        max_exclusive="17.0",
        rationale_keyword="3.11",
        why=(
            "websockets 17.0 requires Python >= 3.11 while this package "
            "promises requires-python >= 3.10 and tests a 3.10 matrix cell"
        ),
    ),
]


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in text.split("."):
        match = re.match(r"\d+", chunk)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def declared_version(hold: Hold) -> str | None:
    path = ROOT / hold.declared_in
    if not path.exists():
        return None
    pattern = re.compile(
        rf"^{re.escape(hold.name)}(\[[^\]]+\])?==(?P<version>[^\s;#]+)",
        re.M | re.I,
    )
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group("version") if match else None


def dependabot_ignores() -> dict[str, list[str]]:
    """Parse the `ignore:` entries without requiring PyYAML.

    Shape produced by the file (and by Dependabot's own docs):

        ignore:
          - dependency-name: "mutmut"
            versions: [">=3.0"]
    """
    if not DEPENDABOT.exists():
        return {}

    found: dict[str, list[str]] = {}
    current: str | None = None
    for raw in DEPENDABOT.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name_match = re.match(
            r"^-?\s*dependency-name:\s*[\"']?([A-Za-z0-9._-]+)[\"']?\s*$", line
        )
        if name_match:
            current = canonical(name_match.group(1))
            found.setdefault(current, [])
            continue
        if current and line.startswith("versions:"):
            found[current].extend(re.findall(r"[><=!~]+\s*[0-9][0-9A-Za-z.*-]*", line))
    return found


def check(hold: Hold) -> list[str]:
    problems: list[str] = []
    path = ROOT / hold.declared_in
    ceiling = version_tuple(hold.max_exclusive)

    # 1. the pin itself
    version = declared_version(hold)
    if version is None:
        problems.append(
            f"{hold.name}: no `{hold.name}==` pin found in {hold.declared_in}. "
            f"Either the file moved or the hold is obsolete — update "
            f"HELD_BACK in this script rather than deleting the guard."
        )
    elif version_tuple(version) >= ceiling:
        problems.append(
            f"{hold.name}=={version} in {hold.declared_in} is at or above "
            f"{hold.max_exclusive}, which is held back on purpose: "
            f"{hold.why}."
        )

    # 2. the machine-readable half
    ignored = dependabot_ignores().get(canonical(hold.name), [])
    satisfied = any(
        spec.startswith(">=") and version_tuple(spec[2:].strip()) <= ceiling
        for spec in ignored
    )
    if not satisfied:
        problems.append(
            f"{hold.name} is held below {hold.max_exclusive} but "
            f".github/dependabot.yml has no matching ignore entry "
            f"(found: {ignored or 'nothing'}). The reason lives in a "
            f"comment the bot cannot read, so it will propose the bump "
            f"again — that is exactly how PR #5 happened."
        )

    # 3. the human-readable half
    #
    # Only the comment block immediately above the pin counts. Scanning
    # the whole file passed `websockets` on the strength of an unrelated
    # note about `async-timeout <3.11` several lines up -- a green that
    # proved nothing, caught by reading the guard's own output instead of
    # trusting it.
    if path.exists() and version is not None:
        lines = path.read_text(encoding="utf-8").splitlines()
        pin_at = next(
            (
                i
                for i, ln in enumerate(lines)
                if re.match(
                    rf"^{re.escape(hold.name)}(\[[^\]]+\])?==", ln, re.I
                )
            ),
            None,
        )
        block: list[str] = []
        if pin_at is not None:
            i = pin_at - 1
            while i >= 0 and lines[i].lstrip().startswith("#"):
                block.append(lines[i])
                i -= 1
        prose = "\n".join(block)
        if hold.rationale_keyword.lower() not in prose.lower():
            problems.append(
                f"the comment block directly above the {hold.name} pin in "
                f"{hold.declared_in} no longer explains the hold (expected "
                f"it to mention '{hold.rationale_keyword}'). A ceiling "
                f"nobody can justify gets raised by the next person who "
                f"reads it."
            )
    return problems


def main() -> int:
    if not HELD_BACK:
        print(
            "no held-back dependencies declared — if that is genuinely true, "
            "delete this guard rather than leaving it reporting OK",
            file=sys.stderr,
        )
        return 2
    if not DEPENDABOT.exists():
        print(
            f"{DEPENDABOT.relative_to(ROOT)} is missing; cannot verify that "
            f"deliberate holds are enforced against the bot",
            file=sys.stderr,
        )
        return 2

    problems: list[str] = []
    for hold in HELD_BACK:
        problems.extend(check(hold))

    if problems:
        print("HELD-BACK DEPENDENCY FAILURES:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    names = ", ".join(h.name for h in HELD_BACK)
    print(
        f"OK: {len(HELD_BACK)} deliberate hold(s) pinned, explained, and "
        f"enforced against Dependabot ({names})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
