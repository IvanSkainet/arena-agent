"""UI Automator dump + element-based tapping for Arena mobile.

Backs the `/v1/mobile/{serial}/ui` and `/v1/mobile/{serial}/tap_by`
endpoints. All UI operations reduce to two adb primitives:

  * `exec-out uiautomator dump /dev/tty` — streams the XML dump straight
    to stdout so we skip the sdcard round-trip that the classic
    `uiautomator dump` + `pull` incurs. Works on Android 6+ and
    HyperOS 3.
  * `input tap` from `arena.mobile.input` — reused for tap_by so
    validation stays in one place.

The dump is intentionally *not* cached: every call collects the current
UI tree, because the whole point of an "AI agent taps a button" flow is
that the state may have changed between two calls. Typical latency on
the reference POCO F7 Pro is ~2.5 s for a home screen dump; caller can
downscope by passing a `path=` filter that only returns matching nodes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run
from arena.mobile.input import tap as _tap

# `[x1,y1][x2,y2]` — the coordinate format uiautomator emits.
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# Attributes we care about for the flat interactive-nodes list. Full
# node dicts include everything from the XML so callers that want the
# raw shape can still get it via `include_full_tree=True`.
_INTERACTIVE_ATTRS = (
    "index", "text", "resource-id", "class", "package", "content-desc",
    "checkable", "checked", "clickable", "enabled", "focusable", "focused",
    "scrollable", "long-clickable", "selected", "hint", "password",
    "bounds", "drawing-order",
)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def dump_ui(
    serial: str,
    *,
    interactive_only: bool = True,
    include_full_tree: bool = False,
    max_nodes: int = 500,
) -> dict[str, Any]:
    """Dump the current UI hierarchy from the device.

    Args:
      serial: adb device serial.
      interactive_only: only return nodes where `clickable`, `long-clickable`
        or `scrollable` is true, OR that carry a non-empty `text` /
        `content-desc`. Reduces a 500-node HyperOS home screen to ~40
        actionable elements, which is what an agent typically wants.
      include_full_tree: return the raw XML dump in `xml` so tooling can
        do its own analysis. Off by default because it doubles the
        response size.
      max_nodes: hard cap on the interactive list to keep responses
        JSON-serialisable without paging. Truncation is reported via
        `truncated: true` in the result.

    Returns:
      {"ok": bool,
       "serial": str,
       "duration_ms": int,
       "root_package": str | None,     # top-level app package name
       "rotation": int,                # 0/1/2/3 from <hierarchy rotation="…">
       "screen_bounds": [w, h] | None, # from the root FrameLayout
       "nodes": [ { ... interactive-nodes ... } ],
       "node_count_total": int,        # includes non-interactive
       "truncated": bool,
       "xml": str | None,              # only when include_full_tree
       "error": str | None,
       "stderr": str | None}
    """
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")
    guard = _ensure_adb()
    if guard:
        return guard

    import time
    started = time.monotonic()
    try:
        # `/dev/tty` here is a well-known uiautomator trick: it prints
        # a status line to /dev/tty then dumps the actual XML to stdout.
        # exec-out gives us the raw binary stream, no CRLF translation.
        r = run(["exec-out", "uiautomator", "dump", "/dev/tty"],
                serial=serial, timeout=30, capture_binary=True)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"ui dump failed: {e}")
    duration_ms = int((time.monotonic() - started) * 1000)

    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
        return _err(stderr or f"uiautomator dump exit {r.returncode}",
                    duration_ms=duration_ms)

    raw = (r.stdout or b"").decode("utf-8", "replace")
    # uiautomator interleaves its own status line
    # ("UI hierchary dumped to: /dev/tty\n") with the XML payload on
    # stdout when we send it through exec-out. Trim off anything before
    # the `<?xml` prolog and anything after the closing `</hierarchy>`.
    idx = raw.find("<?xml")
    if idx > 0:
        raw = raw[idx:]
    if not raw.lstrip().startswith("<?xml"):
        return _err("uiautomator returned no XML",
                    duration_ms=duration_ms,
                    stdout_head=raw[:200])
    end = raw.rfind("</hierarchy>")
    if end >= 0:
        raw = raw[: end + len("</hierarchy>")]

    # v4.42.0: defence-in-depth against a rogue uiautomator dump.
    # Legitimate dumps never carry a DOCTYPE / DTD; if one is
    # present it is either a malformed dump (harmless) or a
    # malicious app trying to trip a billion-laughs / external-
    # entity attack against the bridge. Reject early. The
    # stdlib ET is not resolver-safe by default (Python does
    # not ship defusedxml in the required deps), so a static
    # substring check on the raw bytes is the simplest safe
    # gate that avoids a hard dependency.
    _lowered = raw.lstrip()[:512].lower()
    if "<!doctype" in _lowered or "<!entity" in _lowered:
        return _err("ui XML rejected: DOCTYPE/entity declarations "
                    "not allowed in uiautomator dumps",
                    duration_ms=duration_ms)
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as e:
        return _err(f"ui XML parse failed: {e}",
                    duration_ms=duration_ms)

    nodes: list[dict[str, Any]] = []
    total = 0
    truncated = False
    root_pkg: str | None = None
    screen_bounds: list[int] | None = None

    for elem in tree.iter("node"):
        total += 1
        # Capture root package and screen bounds from the first non-hierarchy
        # node we encounter (the outermost FrameLayout).
        if root_pkg is None:
            pkg = elem.get("package") or ""
            if pkg:
                root_pkg = pkg
                b = _parse_bounds(elem.get("bounds", ""))
                if b:
                    screen_bounds = [b[2] - b[0], b[3] - b[1]]

        if interactive_only and not _is_interactive(elem):
            continue

        node = {k: elem.get(k, "") for k in _INTERACTIVE_ATTRS}
        b = _parse_bounds(node.get("bounds", ""))
        if b:
            x1, y1, x2, y2 = b
            node["bounds_rect"] = [x1, y1, x2, y2]
            node["center"] = [(x1 + x2) // 2, (y1 + y2) // 2]
            node["width"] = max(0, x2 - x1)
            node["height"] = max(0, y2 - y1)
        nodes.append(node)
        if len(nodes) >= max_nodes:
            truncated = True
            break

    result: dict[str, Any] = {
        "ok": True,
        "serial": serial,
        "duration_ms": duration_ms,
        "root_package": root_pkg,
        "rotation": _safe_int(tree.get("rotation"), 0),
        "screen_bounds": screen_bounds,
        "nodes": nodes,
        "node_count_total": total,
        "truncated": truncated,
    }
    if include_full_tree:
        result["xml"] = raw
    return result


def _is_interactive(elem: ET.Element) -> bool:
    """Heuristic for 'actionable' nodes agents would want to see."""
    if _true(elem.get("clickable")) or _true(elem.get("long-clickable")):
        return True
    if _true(elem.get("scrollable")):
        return True
    if _true(elem.get("checkable")) or _true(elem.get("focusable")):
        return True
    # A pure-text node (label) is worth including so the agent can read
    # the current screen even if it can't tap it directly. Same for
    # non-empty content descriptions (accessibility text).
    if (elem.get("text") or "").strip() or (elem.get("content-desc") or "").strip():
        return True
    return False


def _true(v: str | None) -> bool:
    return (v or "").strip().lower() == "true"


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS_RE.search(raw or "")
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# tap_by — find a node by selector and tap its centre.
# ---------------------------------------------------------------------------

_SELECTOR_KEYS = ("id", "text", "desc", "class_name", "package", "index")


def tap_by(
    serial: str,
    *,
    id: str | None = None,
    text: str | None = None,
    desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
    index: int | None = None,
    match: str = "exact",   # "exact" | "contains" | "regex"
) -> dict[str, Any]:
    """Tap the first UI element matching the given selector.

    At least one of `id`/`text`/`desc`/`class_name` must be non-empty.
    `index` picks the Nth match when several nodes satisfy the selector
    (0-based, in dump order). `package` further scopes matches to a
    specific app so that a stale window from another app doesn't win.

    Returns the standard tap-result envelope with additional fields:
      * matched: {id, text, desc, class, bounds_rect, center}
      * candidates: int total matches (helpful when index picked one out
        of many)
    """
    if not any([id, text, desc, class_name]):
        return _err(
            "tap_by requires at least one of: id, text, desc, class_name",
            hint="Example: tap_by(id='com.android.settings:id/search_btn')",
        )
    if match not in ("exact", "contains", "regex"):
        return _err(f"invalid match mode: {match!r}",
                    hint="Use 'exact', 'contains' or 'regex'.")

    dump = dump_ui(serial, interactive_only=False, max_nodes=2000)
    if not dump.get("ok"):
        return dump

    matcher = _make_matcher(match)
    candidates: list[dict[str, Any]] = []
    for n in dump["nodes"]:
        if id and not matcher(n.get("resource-id", ""), id):
            continue
        if text and not matcher(n.get("text", ""), text):
            continue
        if desc and not matcher(n.get("content-desc", ""), desc):
            continue
        if class_name and not matcher(n.get("class", ""), class_name):
            continue
        if package and (n.get("package") or "") != package:
            continue
        candidates.append(n)

    if not candidates:
        return _err(
            "no UI element matched",
            selector={"id": id, "text": text, "desc": desc,
                      "class_name": class_name, "package": package,
                      "match": match, "index": index},
            candidates=0,
            hint=("Call GET /v1/mobile/{serial}/ui to see what is on "
                  "screen right now — the UI may have changed since you "
                  "last checked."),
        )

    pick_idx = index if isinstance(index, int) else 0
    if pick_idx < 0 or pick_idx >= len(candidates):
        return _err(
            f"index {pick_idx} out of range (matched {len(candidates)})",
            candidates=len(candidates),
        )
    picked = candidates[pick_idx]
    center = picked.get("center")
    if not center or len(center) != 2:
        return _err(
            "matched node has no bounds — nothing to tap",
            matched=picked,
        )
    x, y = int(center[0]), int(center[1])
    res = _tap(serial, x, y)
    res = dict(res)
    res["action"] = "tap_by"
    res["matched"] = {
        "id": picked.get("resource-id"),
        "text": picked.get("text"),
        "desc": picked.get("content-desc"),
        "class": picked.get("class"),
        "package": picked.get("package"),
        "bounds_rect": picked.get("bounds_rect"),
        "center": center,
    }
    res["candidates"] = len(candidates)
    res["picked_index"] = pick_idx
    return res


def _make_matcher(mode: str):
    """Return a fn(value_from_dump, wanted) -> bool for the given mode."""
    if mode == "exact":
        return lambda v, w: (v or "") == w
    if mode == "contains":
        return lambda v, w: w in (v or "")
    if mode == "regex":
        def _rx(v: str, w: str) -> bool:
            try:
                return re.search(w, v or "") is not None
            except re.error:
                return False
        return _rx
    return lambda v, w: (v or "") == w  # fallback: exact
