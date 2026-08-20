"""Mission identifier parsing shared by every mission GET endpoint (#130).

Three surfaces disagreed about how a mission is named, and the
disagreement was load-bearing rather than cosmetic:

* the MCP tools declare ``{"mission_id": ..., "name": ...}`` in their
  input schemas and normalise one to the other before calling the
  bridge (``arena/mcp/tool_mission.py``);
* the REST handlers read ``name`` only;
* the REST 400 body says ``missing required parameter 'name' (or
  'mission_id')`` and offers ``mission_id`` as an accepted key.

So a client that followed the error message it had just been handed got
another 400 with the same message -- an unbreakable loop, and the worst
kind of API defect, because the API itself is the thing telling the
client to do the failing action.

``scenario.list`` deepened it: it reports every scenario twice, as a
short ``name`` (``armed-posture-live-proof-41470``) and a prefixed
``mission_id`` (``scenario-armed-posture-live-proof-41470``). Only the
prefixed spelling exists on disk, so the field literally called ``name``
404s against the endpoint whose parameter is literally called ``name``.

This module is the single place that answers "which mission did the
caller mean". Both aliases are accepted, and a short scenario name is
resolved to its stored directory. Keeping it in one module (rather than
in each handler) is deliberate: the previous state of the world *was*
per-handler parsing, and that is how the three surfaces drifted apart.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

#: Query keys accepted for a mission identifier, in priority order.
#: ``name`` wins when both are supplied and disagree -- it is the
#: parameter the endpoint documents in its own hint, so honouring it
#: keeps the documented spelling authoritative.
IDENTIFIER_KEYS: tuple[str, ...] = ("name", "mission_id")

#: Prefix the scenario templates prepend when they persist a mission.
#: ``scenario.list`` exposes the unprefixed form as ``name``; the store
#: only ever holds the prefixed one.
SCENARIO_PREFIX = "scenario-"


def parse_mission_identifier(query_string: str) -> str:
    """Return the mission identifier from a raw query string.

    Accepts either ``name`` or ``mission_id``. Returns ``""`` when
    neither is present or both are blank, which callers turn into the
    400 that names both spellings.
    """
    query = parse_qs(query_string)
    for key in IDENTIFIER_KEYS:
        value = query.get(key, [""])[0]
        if value:
            return value
    return ""


def resolve_mission_name(missions_dir: Path, name: str) -> str:
    """Map a caller-supplied identifier onto the stored mission name.

    Returns ``name`` unchanged when it already exists on disk, or when
    no prefixed variant exists -- an unknown mission must still produce
    the 404 that names what the caller actually asked for, not a
    silently rewritten identifier.

    The only rewrite is the scenario prefix: ``scenario.list`` hands out
    a short ``name`` that the mission store does not have, and resolving
    it here is what makes the discovery-to-status flow work.
    """
    if not name or _looks_unsafe(name):
        return name
    try:
        if (missions_dir / name).exists():
            return name
        candidate = f"{SCENARIO_PREFIX}{name}"
        if not name.startswith(SCENARIO_PREFIX) and (missions_dir / candidate).exists():
            return candidate
    except OSError:
        # A stat failure (permissions, a vanished mount) must not turn a
        # lookup into a 500: fall through and let the caller's own
        # not-found path report it.
        return name
    return name


def _looks_unsafe(name: str) -> bool:
    """Reject traversal before touching the filesystem.

    ``mission_dir`` validates too, but this module stats paths *before*
    that check runs, so it must not be the weak link: a ``name`` of
    ``../../etc`` would otherwise have its existence probed here.
    """
    return ".." in name or "/" in name or "\\" in name or name.startswith(".")
