"""Resolve OCR text hits into desktop window targets."""
from __future__ import annotations

from typing import Any

from arena.desktop.displays import get_displays, match_display
from arena.desktop.text_matching import point_in_geometry
from arena.desktop.window_catalog import list_desktop_windows, window_candidates


async def resolve_text_window_target(
    *,
    query: str,
    display: str = "",
    window_title: str = "",
    class_contains: str = "",
    desktop_file: str = "",
    resource_name: str = "",
    pid: int | None = None,
    scale: float | None = None,
    max_width: int | None = None,
    quality: int = 80,
    min_confidence: int = 40,
    psm: int = 11,
    max_results: int = 20,
    prefer_active_window: bool = True,
    within_active_window: bool = False,
    crop_active_window: bool = False,
    require_active_title: str = "",
    max_window_candidates: int = 5,
    capture_screenshot,
    desktop_exec,
    detect_env,
    get_active_window,
    kwin_windows_via_script,
    ocr_desktop,
    audit_fn=None,
) -> dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "missing query", "status": 400}

    active_window = None
    if prefer_active_window or within_active_window or require_active_title:
        active_window = await get_active_window()
        if require_active_title and (
            not active_window or require_active_title.lower() not in str(active_window.get("title", "")).lower()
        ):
            return {
                "ok": False,
                "error": "input_guard_failed",
                "message": "Active window does not match required title",
                "active_window": active_window,
                "required_title_contains": require_active_title,
                "status": 409,
            }

    display_info = None
    displays_result = await get_displays(desktop_exec=desktop_exec)
    displays = list(displays_result.get("displays") or [])
    if display:
        display_info = match_display(displays, display)
        if not display_info:
            return {
                "ok": False,
                "error": f"unknown display: {display}",
                "available_displays": displays,
                "status": 404,
            }

    crop_geometry = None
    if display_info:
        crop_geometry = display_info.get("geometry")
    elif crop_active_window and active_window:
        crop_geometry = active_window.get("geometry")

    ocr_result = await ocr_desktop(
        query=query,
        scale=scale,
        max_width=max_width,
        quality=quality,
        min_confidence=min_confidence,
        psm=psm,
        max_results=max_results,
        prefer_active_window=prefer_active_window,
        within_active_window=within_active_window,
        active_window=active_window,
        region_x=(crop_geometry or {}).get("x"),
        region_y=(crop_geometry or {}).get("y"),
        region_width=(crop_geometry or {}).get("width"),
        region_height=(crop_geometry or {}).get("height"),
        capture_screenshot=capture_screenshot,
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        audit_fn=audit_fn,
    )
    if not ocr_result.get("ok"):
        return ocr_result
    best_match = ocr_result.get("best_match")
    if not best_match:
        return {**ocr_result, "ok": False, "error": f"no matches for query: {query}", "status": 404}

    windows_result = await list_desktop_windows(
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        kwin_windows_via_script=kwin_windows_via_script,
    )
    filtered_windows = window_candidates(
        list(windows_result.get("windows") or []),
        title=window_title,
        class_contains=class_contains,
        desktop_file=desktop_file,
        resource_name=resource_name,
        pid=pid,
        display=display,
        active_only=False,
    )
    center = best_match.get("center") or {}
    containing = []
    for window in filtered_windows:
        if point_in_geometry(center, window.get("geometry")):
            area = int(window["geometry"]["width"]) * int(window["geometry"]["height"])
            containing.append((not bool(window.get("active")), area, window))
    containing.sort(key=lambda item: (item[0], item[1]))
    containing_windows = [window for _, _, window in containing[: max(1, int(max_window_candidates or 5))]]
    target_window = containing_windows[0] if containing_windows else None
    result = {
        **ocr_result,
        "query": query,
        "display": display_info,
        "active_window": active_window,
        "target_window": target_window,
        "window_candidates": containing_windows,
        "filtered_window_count": len(filtered_windows),
        "displays": displays,
        "crop_active_window": bool(crop_active_window),
        "crop_region": crop_geometry,
        "windows_backend": windows_result.get("tool") or windows_result.get("backend"),
    }
    if not target_window:
        return {**result, "ok": False, "error": "no containing window for matched text", "status": 404}
    return result


__all__ = ["resolve_text_window_target"]
