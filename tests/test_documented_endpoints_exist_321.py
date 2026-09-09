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

The reverse direction is deliberately not checked. The registry holds
several hundred routes; demanding prose for every one of them produces a
wall of failures about internal endpoints nobody meant to document, and a
gate that noisy gets deleted within a month. No count is quoted here on
purpose -- a number in a comment is exactly the kind of thing that goes
stale and then contradicts the parser twenty lines below it.
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
# Dots are legal inside a placeholder and nowhere else. `{path:.*}` is a real
# registered shape (`/v1/code/runs/{run_id}/artifacts/{path:.*}`), while
# `/v1/tunnels/active.public_url` is a JSON field of the response from
# `/v1/tunnels/active` and prose writes it that way -- treating that as a
# route invents one nobody claimed existed.
#
# Excluding dots everywhere was the first attempt and it left a hole: a
# documented route ending in `{path:.*}` did not match at all, so an invented
# one would have been skipped rather than caught.
_DOC_PATH = re.compile(
    r"`(/v1(?:/(?:[A-Za-z0-9_-]+|\{[^}`]+\}))*)`")

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


def _is_prose(doc: pathlib.Path) -> bool:
    """A file whose endpoint mentions are claims about the current build."""
    relative = doc.relative_to(REPO_ROOT).as_posix()
    return doc.is_file() and not relative.startswith(DOC_EXCLUDE)


def _prose_files() -> list[pathlib.Path]:
    """Every such document, each one once.

    Deduplicated by relative path because the globs may overlap: a file
    matched by two patterns would otherwise be read and scanned twice.
    """
    matched = (
        doc
        for pattern in DOC_GLOBS
        for doc in REPO_ROOT.glob(pattern)
    )
    seen = {
        doc.relative_to(REPO_ROOT).as_posix(): doc
        for doc in matched
        if _is_prose(doc)
    }
    return [seen[key] for key in sorted(seen)]


def _documented_paths() -> dict[str, list[str]]:
    """Paths mentioned in prose, mapped to where each was mentioned."""
    found: dict[str, list[str]] = {}
    for doc in _prose_files():
        where = doc.relative_to(REPO_ROOT).as_posix()
        text = doc.read_text(encoding="utf-8", errors="replace")
        for raw in _DOC_PATH.findall(text):
            sources = found.setdefault(_placeholders_normalised(raw), [])
            if where not in sources:
                sources.append(where)
    return found


def test_the_wiki_glob_is_not_dead_weight() -> None:
    """`.cubic/wiki` is absent today, and that has to stay visible.

    The gate was written because a generated wiki invented three endpoints
    (#265, #321). That wiki is not in the tree: the sync PR is unmerged, so
    the glob matches nothing and the case this exists for is not covered by
    the run -- only `docs/`, `README.md` and `AGENTS.md` are.

    Asserting the absence is not a way of pretending it is covered. It is a
    tripwire: whichever way the directory arrives -- the sync PR merged, a
    hand-written page, a bot -- this fails and says the coverage claim just
    changed and the glob now has to earn its place. Silence, in a file whose
    whole subject is claims that nobody re-checks, would be the wrong
    default.
    """
    wiki = REPO_ROOT / ".cubic" / "wiki"
    pages = sorted(wiki.rglob("*.md")) if wiki.is_dir() else []
    assert not pages, (
        f"{len(pages)} wiki pages exist now, so the `.cubic/wiki/**/*.md` "
        "entry in DOC_GLOBS is live. Confirm this gate actually reads them "
        "-- generated pages are the reason it was written -- then delete "
        "this test, which only asserts they were absent."
    )


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
