"""Top-level window enumeration for the Windows desktop backend.

Split out of `windows.py` under #351, which took that module past the
600-line `MAX_RUNTIME_LINES` threshold. Enumeration is a self-contained
concern -- walk `EnumWindows`, describe each window, apply the
`visible_only` filter -- and it is the part the issue is about, so it
is the part that moves.

`windows.py` re-exports these names, so callers and the backend's
public surface are unchanged.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import sys
from typing import Any

from arena.desktop.backends import _win32_api as _api

user32 = _api.user32
dwmapi = _api.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9
_IS_WINDOWS = sys.platform == "win32"

logger = logging.getLogger(__name__)


def _rect_to_geometry(rect: wt.RECT) -> dict[str, int]:
    return {
        "x": int(rect.left),
        "y": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def _geometry_area(geom: dict[str, int] | None) -> int:
    if not geom:
        return 0
    return max(0, int(geom.get("width") or 0)) * max(0, int(geom.get("height") or 0))


def _client_rect_geometry(hwnd: int) -> dict[str, int] | None:
    rect = wt.RECT()
    if not user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    pt = wt.POINT(0, 0)
    if not user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt)):
        return None
    return {"x": int(pt.x), "y": int(pt.y), "width": width, "height": height}


def _dwm_frame_geometry(hwnd: int) -> dict[str, int] | None:
    """The DWM extended frame bounds, or None when unavailable.

    Split out of `_window_rect_geometry` under #351: the nesting there
    crossed CodeScene's threshold once the module moved. The `OSError`
    is what a ctypes call into a missing or refusing `dwmapi` raises;
    it means "no DWM answer", which is what the `None` says, so it is
    logged at debug rather than swallowed silently.
    """
    if dwmapi is None:
        return None
    try:
        dwm_rect = wt.RECT()
        hr = dwmapi.DwmGetWindowAttribute(
            wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(dwm_rect), ctypes.sizeof(dwm_rect)
        )
    except OSError as exc:
        logger.debug("[desktop] dwm frame bounds unavailable for hwnd %s: %s", hwnd, exc)
        return None
    dwm_geom = _rect_to_geometry(dwm_rect)
    if hr == 0 and _geometry_area(dwm_geom) > 0:
        return dwm_geom
    return None


def _window_rect_geometry_or_none(hwnd: int) -> dict[str, int] | None:
    """`GetWindowRect` as a measurement, or None when the call failed.

    A zero return leaves the `RECT` at its defaults, and passing those
    on labelled `get_window_rect` claims an authority the call never
    gave -- raised in review. Reported as None so the caller treats it
    the same as any other source that had no answer.
    """
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        logger.debug("[desktop] GetWindowRect failed for hwnd %s", hwnd)
        return None
    return _rect_to_geometry(rect)


def _window_rect_geometry(hwnd: int) -> tuple[dict[str, int], str]:
    """The best geometry available for a window, and where it came from.

    Written as a flat list of sources in order of preference rather
    than nested conditionals: CodeScene flagged the nesting twice, and
    the second time it was because the `GetWindowRect` failure path had
    grown its own copy of the client-rect fallback. One chain, one
    fallback, one place to change it.
    """
    dwm_geom = _dwm_frame_geometry(hwnd)
    if dwm_geom is not None:
        return dwm_geom, "dwm_extended_frame_bounds"
    window_geom = _window_rect_geometry_or_none(hwnd)
    if window_geom is not None and _geometry_area(window_geom) > 0:
        return window_geom, "get_window_rect"
    client = _client_rect_geometry(hwnd)
    if client:
        return client, "client_rect"
    if window_geom is not None:
        # A real measurement that happens to be empty: a collapsed or
        # zero-sized window is a fact about the window, not a failure.
        return window_geom, "get_window_rect"
    return {"x": 0, "y": 0, "width": 0, "height": 0}, "unavailable"


def _select_best_visual_child(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [c for c in candidates if c.get("visible") and _geometry_area(c.get("geometry")) > 0]
    if not usable:
        return None
    usable.sort(key=lambda c: (_geometry_area(c.get("geometry")), bool(c.get("title"))), reverse=True)
    return usable[0]


def _child_window_candidates(hwnd: int, owner_pid: int | None = None) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []

    def _proc(child: int, _lparam: int) -> bool:
        try:
            visible = bool(user32.IsWindowVisible(child))
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
            if owner_pid is not None and int(pid.value) != int(owner_pid):
                return True
            title_len = user32.GetWindowTextLengthW(child)
            title_buf = ctypes.create_unicode_buffer(title_len + 2)
            user32.GetWindowTextW(child, title_buf, title_len + 2)
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child, cls_buf, 256)
            geom, source = _window_rect_geometry(child)
            children.append({
                "id": str(child),
                "title": title_buf.value or "",
                "class": cls_buf.value or "",
                "pid": int(pid.value),
                "geometry": geom,
                "visible": visible,
                "minimized": bool(user32.IsIconic(child)),
                "geometry_source": source,
            })
        except OSError as exc:
            # Expected: a child window can close between being
            # enumerated and being measured. Raising would abort
            # `EnumChildWindows` and drop every sibling, so enumeration
            # continues -- quietly, because this is normal.
            logger.debug("[desktop] skipping child hwnd %s of %s: %s", child, hwnd, exc)
        except Exception:
            # Not expected: a `TypeError` or `KeyError` here is a bug in
            # this module, not a window disappearing. It still must not
            # cross the ctypes callback boundary, but it must not hide
            # at debug either -- raised in review, and right: a
            # programmer error showing up as "fewer child windows" is
            # how this stays unnoticed.
            logger.warning(
                "[desktop] unexpected failure describing child hwnd %s of %s", child, hwnd, exc_info=True
            )
        return True

    cb = _api.EnumWindowsProc(_proc)
    user32.EnumChildWindows(wt.HWND(hwnd), cb, 0)
    return children


def _best_window_geometry(hwnd: int, owner_pid: int | None = None) -> tuple[dict[str, int], dict[str, Any] | None, str]:
    """Return visual geometry, using child windows when owner geometry is bogus."""
    geom, source = _window_rect_geometry(hwnd)
    if _geometry_area(geom) > 0:
        return geom, None, source
    child = _select_best_visual_child(_child_window_candidates(hwnd, owner_pid=owner_pid))
    if child:
        return child["geometry"], child, f"child_window:{child.get('geometry_source', 'unknown')}"
    return geom, None, source


# ---------------------------------------------------------------------------
# Window listing
# ---------------------------------------------------------------------------
_SHELL_WINDOW_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "IME"})


def _is_untitled_shell_window(title: str, cls: str) -> bool:
    """Is this the desktop, the taskbar or the IME rather than a window?

    Extracted from the inline condition in `list_windows` for #351.
    This rule is why `list_windows()` and `get_active_window()` can
    name different foreground windows -- the taskbar holds the focus
    whenever the suite runs from a background process -- and while it
    lived inline the only thing covering it was a Windows-only live
    test. As a function it is checked on every platform in CI.
    """
    return not title and cls in _SHELL_WINDOW_CLASSES


def _window_text(hwnd: int) -> tuple[str, str]:
    """The title and class name of a window, each possibly empty."""
    title_len = user32.GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(title_len + 2)
    user32.GetWindowTextW(hwnd, title_buf, title_len + 2)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    return title_buf.value or "", cls_buf.value or ""


def _describe_window(hwnd: int, *, foreground: int, visible_only: bool) -> dict[str, Any] | None:
    """One window as a dict, or None when the filter excludes it.

    Split out of the `EnumWindows` callback so the callback is a loop
    body and this is the description of a window. `foreground` is
    passed in rather than read here: it must be the single snapshot the
    whole enumeration is compared against (#351), and reading it per
    window would reintroduce the race this issue is about.
    """
    visible = bool(user32.IsWindowVisible(hwnd))
    if visible_only and not visible:
        return None
    title, cls = _window_text(hwnd)
    if visible_only and _is_untitled_shell_window(title, cls):
        return None
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    geometry, visual_child, geometry_source = _best_window_geometry(hwnd, owner_pid=int(pid.value))
    item: dict[str, Any] = {
        "id": str(hwnd),
        "title": title,
        "class": cls,
        "pid": int(pid.value),
        "geometry": geometry,
        "visible": visible,
        "minimized": bool(user32.IsIconic(hwnd)),
        "active": hwnd == foreground,
        "geometry_source": geometry_source,
    }
    if visual_child:
        item["visual_child"] = visual_child
        item["visual_id"] = visual_child.get("id")
        item["visual_class"] = visual_child.get("class")
        item["visual_title"] = visual_child.get("title")
    return item


def list_windows_with_foreground(*, visible_only: bool = True) -> tuple[list[dict[str, Any]], int]:
    """`list_windows`, plus the foreground HWND it compared against.

    Added for #351. `active` is set from one `GetForegroundWindow()`
    read taken inside the enumeration, and a caller wanting to
    cross-check the flag had no way to name that value: reading the API
    again returns a *different* snapshot, and focus that leaves and
    comes back during the walk (A->B->A) makes two outer reads agree
    while the flag holds B.

    Returned rather than stashed on the module. A module-global would
    be shared state: these backend functions run under
    `run_in_executor`, so a concurrent enumeration on another worker
    could overwrite the value between a caller's own call and its read.
    A return value belongs to the call that produced it.
    """
    return _enumerate_windows(visible_only=visible_only)


def _enumerate_windows(*, visible_only: bool = True) -> tuple[list[dict[str, Any]], int]:
    """Enumerate top-level windows.

    Returns a list of dicts with:
    - ``id``: HWND as a decimal string
    - ``title``: window title
    - ``class``: window class name
    - ``pid``: owning process id
    - ``geometry``: {x, y, width, height}
    - ``visible``: bool
    - ``minimized``: bool
    - ``active``: bool (is this the foreground window)
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")

    # `GetForegroundWindow` is declared `restype = wt.HWND`, i.e.
    # `c_void_p`, and ctypes turns a NULL return into `None` rather
    # than 0. Windows really does return NULL when nothing holds the
    # focus -- a locked screen, or the moment between one window losing
    # it and the next taking it -- so the value is normalised here.
    # Without it `int(fg)` raised `TypeError` out of `list_windows`
    # and the window-list endpoint, on exactly the desktop state #351
    # is about. Raised in review; `hwnd == fg` below is unaffected
    # either way, since no enumerated window has HWND 0.
    fg = int(user32.GetForegroundWindow() or 0)
    results: list[dict[str, Any]] = []

    def _proc(hwnd: int, _lparam: int) -> bool:
        try:
            item = _describe_window(hwnd, foreground=fg, visible_only=visible_only)
        except OSError as exc:
            # Expected: a window can vanish between being enumerated
            # and being described. Must not propagate -- this is a
            # ctypes callback inside `EnumWindows`, and raising across
            # that boundary aborts the walk and loses every window, not
            # just this one.
            logger.debug("[desktop] skipping hwnd %s: %s", hwnd, exc)
        except Exception:
            # Not expected: a bug in this module rather than a window
            # closing. Same boundary constraint, louder report.
            logger.warning("[desktop] unexpected failure describing hwnd %s", hwnd, exc_info=True)
        else:
            if item is not None:
                results.append(item)
        return True

    cb = _api.EnumWindowsProc(_proc)
    user32.EnumWindows(cb, 0)
    return results, fg


def list_windows(*, visible_only: bool = True) -> list[dict[str, Any]]:
    """Enumerate top-level windows. See `_enumerate_windows` for the fields."""
    windows, _foreground = _enumerate_windows(visible_only=visible_only)
    return windows


