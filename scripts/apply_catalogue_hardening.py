"""One-shot fixer for the catalogue hardening v4.67.0.

Walks the registry files in arena/mcp/ and adds
``"additionalProperties": False`` to every object-typed
inputSchema block that doesn't already have it. Fully
idempotent — running it twice produces zero diff on the
second pass.

Strategy: regex-based, looking for the closing brace of
each ``"inputSchema": {"type": "object", ... `` block. We
match the schema opener, then walk forward tracking brace
depth. The state machine is simple — inputSchema blocks
in this codebase are always dict literals with a single
top-level ``{`` and a matching ``}``.

This is a one-shot script: it's the mechanical bit of the
v4.67.0 release commit. The script is checked in so the
diff itself is auditable (vs. a hand-rewrite of 125
entries across 9 files), but it's not part of the running
test surface.

Usage (maintainer only):
    python scripts/apply_catalogue_hardening.py --repo-root .
    git diff arena/mcp/  # review
    git add -p arena/mcp/
    git commit -m "chore(catalogue): add additionalProperties: false to N tool entries"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Files that contain *_MCP_TOOLS = [...] blocks.
REGISTRY_FILES = [
    "arena/mcp/tool_registry.py",
    "arena/mcp/tool_registry_asr.py",
    "arena/mcp/tool_registry_mission.py",
    "arena/mcp/tool_registry_mobile.py",
    "arena/mcp/tool_registry_net.py",
    "arena/mcp/tool_registry_scenarios.py",
    "arena/mcp/tool_desktop_input.py",
    "arena/mcp/tool_mobile_ext.py",
    "arena/mcp/tool_browser_headed.py",
]


def _has_top_level_key(body: str, key: str) -> bool:
    """Return True if ``body`` has ``key`` as a top-level dict key.

    "Top-level" means: at brace-depth 0 within ``body``. Nested
    dicts that happen to use the same key (e.g. a sub-schema
    inside ``properties.headers.additionalProperties``) are
    ignored.

    This is a small stateful parser: walk ``body`` tracking
    brace depth and string state, and look for ``key:`` only
    when depth == 0.
    """
    depth = 0
    in_string = False
    string_quote = ""
    escape = False
    i = 0
    n = len(body)
    key_bytes = key.encode("utf-8")  # for byte-level match
    body_bytes = body.encode("utf-8")
    while i < n:
        ch = body[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_quote:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                string_quote = ch
                # Are we at depth 0, just opened a string, and the
                # next chars match `key`? (UTF-8 single-byte chars
                # only here — all our keys are ASCII.)
                if depth == 0 and body_bytes[i:i + len(key_bytes)] == key_bytes:
                    # Check the character AFTER the key: must be whitespace or colon.
                    j = i + len(key_bytes)
                    while j < n and body[j] in " \t":
                        j += 1
                    if j < n and body[j] == ":":
                        return True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        i += 1
    return False


def _add_additional_properties(src: str) -> tuple[str, int]:
    """Return (new_src, insertions).

    The pattern we match is:

        "inputSchema": { ... "type": "object" ... }

    where the ``...`` is the body of the dict literal (no
    nested dicts on the same line as the opener). We add
    ``, "additionalProperties": False`` right before the
    closing ``}`` of the dict if the body contains
    ``"type": "object"`` and does NOT already contain
    ``"additionalProperties"``.
    """
    insertions = 0
    out: list[str] = []
    i = 0
    n = len(src)

    while i < n:
        # Look for the schema opener
        m = re.match(r'"inputSchema"\s*:\s*\{', src[i:])
        if not m:
            out.append(src[i])
            i += 1
            continue

        # We have an opener. Find the matching close brace,
        # respecting nested braces and string literals.
        out.append(src[i:i + m.end()])
        i += m.end()
        depth = 1
        body_start = i
        in_string = False
        string_quote = ""
        escape = False
        while i < n and depth > 0:
            ch = src[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == string_quote:
                    in_string = False
            else:
                if ch in ('"', "'"):
                    in_string = True
                    string_quote = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
            i += 1

        body = src[body_start:i]
        closing_brace_idx = i
        # Check: does body contain "type": "object" AND no TOP-LEVEL
        # "additionalProperties"? We only count a top-level key —
        # nested `additionalProperties` on a `headers` or `params`
        # sub-schema is unrelated to the top-level hardening
        # contract and must not suppress the insertion.
        is_object = bool(re.search(r'"type"\s*:\s*"object"', body))
        has_top_level_additional = _has_top_level_key(body, '"additionalProperties"')
        if is_object and not has_top_level_additional:
            # Strip trailing whitespace+comma from body so we can decide
            # whether the new key needs a leading comma. The dict
            # literal style in this codebase is
            #     "key": value,
            #     "last": value,
            # }
            # so body always ends with a comma — but we handle both
            # styles (with and without trailing comma) defensively.
            stripped = body.rstrip()
            if stripped.endswith(","):
                out.append(stripped)
                out.append(' "additionalProperties": False')
            elif stripped.endswith(":") or stripped.endswith("{") or not stripped:
                out.append(stripped)
                out.append('"additionalProperties": False')
            else:
                out.append(stripped + ",")
                out.append(' "additionalProperties": False')
            insertions += 1
        else:
            out.append(body)
        out.append(src[closing_brace_idx])
        i = closing_brace_idx + 1

    return "".join(out), insertions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    total = 0
    for relpath in REGISTRY_FILES:
        path = repo_root / relpath
        if not path.exists():
            print(f"  {relpath}: not found, skipping")
            continue
        src = path.read_text(encoding="utf-8")
        new_src, insertions = _add_additional_properties(src)
        if insertions:
            path.write_text(new_src, encoding="utf-8")
            print(f"  {relpath}: +{insertions} additionalProperties: False")
            total += insertions
    print(f"\n[apply-catalogue-hardening] total insertions: {total}")
    if total == 0:
        print("[apply-catalogue-hardening] all schemas already hardened — nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
