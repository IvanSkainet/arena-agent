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

import os
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


# What a single path component may weigh. 255 of them either way, but the
# unit differs: ext4 and APFS count bytes of UTF-8, NTFS counts UTF-16 code
# units, so `"\U0001f600" * 64` is 256 bytes (refused on Linux) and 128
# units (accepted on Windows). Measuring in the local unit rather than the
# strictest one keeps the bridge from refusing ids that its own filesystem
# would have taken (cubic, sourcery).
NAME_MAX_UNITS = 255


def _component_units(name: str) -> int:
    """How long this name is in the unit the local filesystem counts in."""
    if os.name == "nt":
        return len(name.encode("utf-16-le", "surrogatepass")) // 2
    return len(name.encode("utf-8", "surrogatepass"))


# What Windows refuses in a path component, and Linux does not. `mkdir`
# answers each of these with an exception rather than a False, measured on
# the bridge's own host: `q?x` and `x|y` are WinError 123, `CON` is
# WinError 267, `a:b` is WinError 3, and `"t "` silently becomes `t`, which
# is worse than a refusal because two ids then name one directory (cubic).
_NT_FORBIDDEN_CHARS = frozenset('<>:"/\\|?*')
_NT_DEVICE_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{d}" for d in "123456789"),
    *(f"LPT{d}" for d in "123456789"),
})


def _nt_refusal(name: str) -> str | None:
    """Why NTFS will not take this component, or None. Only asked on nt.

    Checked per-platform for the same reason the length is: `report?` is a
    perfectly good directory name on ext4, and refusing it everywhere would
    have the bridge turn down ids its own filesystem accepts.
    """
    if any(ch in _NT_FORBIDDEN_CHARS for ch in name):
        return "contains a character Windows forbids in a name: <>:\"/\\|?*"
    if any(ord(ch) < 32 for ch in name):
        return "contains a control character Windows forbids in a name"
    if name[-1] in ". " if name else False:
        # Windows strips these silently, so `mission.` and `mission` would
        # be the same directory -- a rename the caller never asked for.
        return "ends with a dot or a space, which Windows drops silently"
    if name.split(".", 1)[0].upper() in _NT_DEVICE_NAMES:
        return "is a reserved DOS device name on Windows"
    return None


def unusable_directory_name(name: str, *, label: str = "mission name") -> str | None:
    """Why this identifier cannot be a directory name, or None if it can.

    Asked before anything touches the filesystem, because the filesystem's
    own answers arrive as exceptions from places no caller expects one --
    `Path.exists()` raising `OSError: [Errno 36]` for an over-long name,
    `mkdir` raising `ValueError` for an embedded NUL, `os.fsencode`
    raising `UnicodeEncodeError` for a lone surrogate, and on Windows
    `WinError 123` for `?` or `|` and `WinError 267` for `CON`. All of
    them left as 500s (#286, then sourcery and cubic over two reviews).

    `label` names the field in the message, because the writer calls its
    parameter `mission_id` and the readers call it `name`; rewriting the
    string afterwards coupled the caller to this function's wording
    (cubic).

    `surrogatepass` on the measurement so that counting a lone surrogate
    does not raise on the way to refusing it.
    """
    if "\x00" in name:
        return f"{label} contains a NUL character"
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in name):
        # A lone surrogate survives JSON decoding and dies at `fsencode`.
        return f"{label} contains an unpaired surrogate"
    if _component_units(name) > NAME_MAX_UNITS:
        unit = "UTF-16 code units" if os.name == "nt" else "bytes"
        return f"{label} is too long: {NAME_MAX_UNITS} {unit} at most"
    if os.name == "nt":
        nt_reason = _nt_refusal(name)
        if nt_reason:
            return f"{label} {nt_reason}"
    return None


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
