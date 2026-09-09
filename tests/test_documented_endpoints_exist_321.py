"""Documented endpoints have to exist.

Why this gate exists
--------------------
PR #265 synced 3619 lines of generated wiki into `.cubic/wiki`. Its
"API Endpoints" table listed three routes that exist nowhere in this
repository:

    POST /v1/exec/command
    GET  /v1/exec/status
    POST /v1/exec/stop

Zero matches across `.py`, `.md`, `.json` and `.yml`. The three real members
of that family -- `POST /v1/exec`, `/v1/exec/stream` and `/v1/kill` -- were
missing from the same table, and the table was signed
`Sources: arena/exec/handlers.py`, a file that contains none of the invented
three. Plausible prose, correct-looking citations, a third of the table made
up.

Nothing caught it. It was found by hand, which does not scale to 26 pages and
will not happen on the next sync.

What this checks, and what it cannot
------------------------------------
Only that a documented path is a path the server actually serves. That is the
part a machine can settle. A wrong method, an invented description of what an
endpoint does, or a claim like "the default timeout is 60 s" all pass this
gate untouched -- documentation is not verified because this is green.

The reverse direction is deliberately not checked. There are 254 routes;
demanding prose for every one of them produces a wall of failures about
internal endpoints nobody meant to document, and a gate that noisy gets
deleted within a month.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

REGISTRY_DIR = REPO_ROOT / "arena" / "route_registry"

# Prose that is expected to describe the public HTTP surface. `.cubic/wiki`
# is generated and overwritten by cubic on every sync, which is exactly why
# this test lives out here in `tests/` -- a fix applied inside that directory
# disappears with the next sync, a failure out here does not.
DOC_GLOBS = (
    ".cubic/wiki/**/*.md",
    "docs/**/*.md",
    "README.md",
    "AGENTS.md",
)

# Dated records of what was observed at a point in time, not statements about
# what the bridge serves today. `docs/audits/*` logs findings against the
# build of the day -- an endpoint that has since been renamed is the finding,
# and rewriting the log to match current code destroys the record. Roadmaps
# are the same: they cite paths precisely because those paths are wrong.
DOC_EXCLUDE = (
    "docs/audits/",
    "docs/STRATEGIC_POSITION_AND_CANONICAL_ROADMAP",
)

# `add_get("/v1/status", ...)` and the `('GET', '/v1/status', ...)` rows in
# registry.py. Both spellings appear in that package.
_ADD_ROUTE = re.compile(
    r"""add_(?:get|post|put|patch|delete|route|view)\(\s*f?["']([^"']+)["']""")
_ROW = re.compile(r"""\(\s*['"][A-Z/]+['"]\s*,\s*['"](/[^'"]+)['"]""")

# A path inside single backticks: `/v1/exec/script`. Anything looser starts
# matching prose that merely mentions a version number.
# No dots: `/v1/tunnels/active.public_url` is a JSON field of the response
# from `/v1/tunnels/active`, and prose writes it that way. Treating it as a
# path invents a route nobody claimed existed. Real paths carry no dot
# outside a `{path:.*}` placeholder, which normalisation removes first.
_DOC_PATH = re.compile(r"`(/v1/[A-Za-z0-9_/{}-]*)`")

# CDP handlers are registered once per prefix through an f-string:
#   _register_cdp_prefix(app, h, "/v1/browser/cdp")
#   _register_cdp_prefix(app, h, "/v1/cdp")
# so the literals in that file read `{prefix}/status`. Grepping for string
# literals alone reports every CDP route as undocumented-and-invented, which
# is a false accusation -- they are real. Expand the prefixes instead.
_PREFIX_CALL = re.compile(
    r"""_register_cdp_prefix\([^)]*?['"]([^'"]+)['"]\s*\)""")


def _placeholders_normalised(path: str) -> str:
    """`/v1/missions/{mission_id}` and `/v1/missions/{id}` are one route.

    The name inside the braces is a local variable, not part of the URL, and
    documentation picks a different one than the registry about half the
    time. Comparing the raw strings turns that into a failure about nothing.
    """
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip("/")) or "/"


def _registered_paths() -> set[str]:
    """Every path the route registry actually wires up."""
    literal: set[str] = set()
    templated: set[str] = set()
    prefixes: set[str] = set()

    for source in sorted(REGISTRY_DIR.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        prefixes.update(_PREFIX_CALL.findall(text))
        for match in _ADD_ROUTE.findall(text) + _ROW.findall(text):
            if "{prefix}" in match:
                templated.add(match)
            elif match.startswith("/"):
                literal.add(match)

    for template in templated:
        for prefix in prefixes:
            literal.add(template.replace("{prefix}", prefix))

    return {_placeholders_normalised(path) for path in literal}


def _documented_paths() -> dict[str, list[str]]:
    """Paths mentioned in prose, mapped to where each was mentioned."""
    found: dict[str, list[str]] = {}
    for pattern in DOC_GLOBS:
        for doc in sorted(REPO_ROOT.glob(pattern)):
            if not doc.is_file():
                continue
            relative = doc.relative_to(REPO_ROOT).as_posix()
            if relative.startswith(DOC_EXCLUDE):
                continue
            text = doc.read_text(encoding="utf-8", errors="replace")
            for raw in _DOC_PATH.findall(text):
                where = str(doc.relative_to(REPO_ROOT))
                found.setdefault(_placeholders_normalised(raw), [])
                if where not in found[_placeholders_normalised(raw)]:
                    found[_placeholders_normalised(raw)].append(where)
    return found


def test_the_registry_is_readable() -> None:
    """A parser that silently finds nothing would make this suite vacuous.

    If the registry is refactored into a shape these patterns do not match,
    `_registered_paths()` returns an empty set, every documented endpoint
    matches nothing, and the real test below would still pass by claiming
    there is nothing to check. Assert the floor instead.
    """
    registered = _registered_paths()
    assert len(registered) > 200, (
        "parsed only "
        f"{len(registered)} routes out of arena/route_registry -- the "
        "registration style probably changed and this gate is now blind"
    )
    # The two CDP prefixes have to survive expansion, since that is the part
    # a naive grep gets wrong.
    for canary in ("/v1/exec/script", "/v1/browser/cdp/eval", "/v1/cdp/eval"):
        assert canary in registered, f"{canary} vanished from the parse"


def test_documented_endpoints_are_real() -> None:
    """Prose may not invent routes the server does not serve."""
    registered = _registered_paths()
    documented = _documented_paths()

    invented = {
        path: sources
        for path, sources in documented.items()
        if path not in registered
    }

    assert not invented, (
        "documentation refers to endpoints that are not in the route "
        "registry:\n"
        + "\n".join(
            f"  {path}  (in {', '.join(sources)})"
            for path, sources in sorted(invented.items())
        )
        + "\nEither the route was removed and the docs are stale, or the "
        "text was generated rather than checked."
    )
