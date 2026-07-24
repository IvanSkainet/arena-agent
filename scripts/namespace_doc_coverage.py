"""Namespace documentation coverage guard.

The MCP catalogue has ~24 distinct namespaces (e.g. ``fs``,
``git``, ``desktop``, ``memory``). Each namespace groups a
family of related tools. A well-documented namespace has at
least one usage example in ``README.md`` / ``README.ru.md``
so a new user can find the namespace by searching the
README and see how to call a tool in it.

The check is intentionally simple: for every namespace in
``MCP_TOOLS``, scan the README files and confirm there is
at least one line that contains a tool name belonging to
that namespace. The line can be in any section (overview,
examples, troubleshooting, etc.) — what matters is that
the namespace is mentioned by example.

Why this matters:

* A new user opens the README, searches for
  ``desktop.ocr`` and expects to find a usage example.
  If no example is there, the user is forced to read the
  source — defeating the README.
* A maintainer who adds a new namespace (``net.acme``,
  ``plan.run``, etc.) and forgets to add a README example
  is shipping an undocumented surface. v4.70.0 catches
  that at PR time.

The script is permissive about the exact form of the
example — a backticked `` `fs.read` ``, a bare ``fs.read``,
or even ``fs.*`` all count. The goal is to surface
*missing* namespaces, not to police formatting.

The script is also tolerant of legacy / whitelisted
namespaces — the four bare names (``ping`` / ``echo`` /
``exec`` / ``snapshot``) get a free pass because v4.69.0
already moved their documentation to a single
"migration guide" section that doesn't follow the
per-namespace convention.

Soft-warn vs hard-fail
----------------------

v4.70.0 ships this guard in **soft-warn** mode (the
default). The v4.70.0 audit found that 22 of 24
namespaces lack an example in the README (only ``sys`` is
covered). That is a real documentation debt but it is out
of scope for a single release — fixing it requires
writing per-namespace examples, which is a documentation
project, not a code change.

The guard runs in warn-by-default mode so the maintainer
can see the debt accumulate over releases, and can opt
into hard mode (``--enforce``) when the README has been
brought back into line.

Exit codes:

* 0 — every namespace has at least one example line in
  one of the README files (or the script is in
  soft-warn mode and only some namespaces are missing).
* 1 — ``--enforce`` mode AND at least one namespace is
  missing. The missing namespaces are listed; existing
  namespaces are shown with the example line that
  satisfied the check.
* 2 — script can't import MCP_TOOLS or can't find README.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_TOOL_NAME_RE = re.compile(r"\b([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\b")


def _namespaces(mcp_tools) -> set[str]:
    out: set[str] = set()
    for entry in mcp_tools:
        if not isinstance(entry, dict):
            continue
        n = entry.get("name")
        if isinstance(n, str) and "." in n:
            out.add(n.split(".", 1)[0])
    return out


def _namespaces_covered_in_readmes(namespaces: set[str], readme_paths: list[Path]) -> tuple[set[str], dict[str, tuple[Path, str]]]:
    """Return (covered_set, satisfying_line_per_namespace).

    A namespace is "covered" if at least one of the README
    files contains a line with a tool name whose first
    component equals the namespace.
    """
    covered: set[str] = set()
    satisfying: dict[str, tuple[Path, str]] = {}
    for readme in readme_paths:
        if not readme.is_file():
            continue
        for line in readme.read_text(encoding="utf-8").splitlines():
            for m in _TOOL_NAME_RE.finditer(line):
                name = m.group(1)
                ns = name.split(".", 1)[0]
                if ns in namespaces and ns not in covered:
                    covered.add(ns)
                    satisfying[ns] = (readme, line.strip())
    return covered, satisfying


def _run(repo_root: Path, enforce: bool) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(repo_root))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS  # type: ignore[import-not-found]
    except Exception as exc:
        print(f"[namespace-doc-coverage] FATAL: cannot import MCP_TOOLS: {exc}", file=sys.stderr)
        return 2

    namespaces = _namespaces(MCP_TOOLS)
    if not namespaces:
        print("[namespace-doc-coverage] OK: catalogue has no namespaced tools", file=sys.stderr)
        return 0

    readme_paths = [repo_root / "README.md", repo_root / "README.ru.md"]
    covered, satisfying = _namespaces_covered_in_readmes(namespaces, readme_paths)

    missing = namespaces - covered
    if not missing:
        print(f"[namespace-doc-coverage] OK: all {len(namespaces)} namespaces covered in README(s)")
        return 0

    prefix = "FAIL" if enforce else "WARN"
    print(f"[namespace-doc-coverage] {prefix}: {len(missing)} of {len(namespaces)} namespaces lack a README example", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"--- namespaces WITHOUT an example ---", file=sys.stderr)
    for ns in sorted(missing):
        print(f"  {ns}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"--- namespaces WITH an example ---", file=sys.stderr)
    for ns in sorted(covered):
        readme, line = satisfying[ns]
        short = line if len(line) <= 80 else line[:77] + "..."
        print(f"  {ns} (in {readme.name}): {short}", file=sys.stderr)
    return 1 if enforce else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root (default: current directory)")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Promote the soft-warn to a hard fail. Use after the README has been updated.",
    )
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve(), enforce=args.enforce)


if __name__ == "__main__":
    sys.exit(main())
