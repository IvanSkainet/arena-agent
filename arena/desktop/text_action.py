"""High-level OCR-to-desktop action workflows."""
from __future__ import annotations

import shutil
from typing import Any

from arena.desktop.input import build_click_command
from arena.desktop.ocr_handler import _target_point
from arena.desktop.text_window_target import resolve_text_window_target
from arena.desktop.window_action import perform_window_action
from arena.desktop.window_action_plans import PLANNED_ACTIONS, plan_window_action_geometry


async def run_text_action(
    *,
    action: str,
    query: str,
    display: str = "",
    target_display: str = "",
    title: str = "",
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
    crop_active_window: bool = True,
    require_active_title: str = "",
    max_window_candidates: int = 5,
    target_position: str = "center",
    offset_x: int = 0,
    offset_y: int = 0,
    button: str = "left",
    double: bool = False,
    activate: bool = True,
    dry_run: bool = False,
    verify: bool = True,
    timeout_ms: int = 1000,
    capture_screenshot,
    desktop_exec,
    detect_env,
    get_active_window,
    kwin_windows_via_script,
    ocr_desktop,
    focus_window,
    kwin_focus_window,
    audit_fn=None,
) -> dict[str, Any]:
    action = str(action or "resolve").strip().lower()
    resolved = await resolve_text_window_target(
        query=query,
        display=display,
        window_title=title,
        class_contains=class_contains,
        desktop_file=desktop_file,
        resource_name=resource_name,
        pid=pid,
        scale=scale,
        max_width=max_width,
        quality=quality,
        min_confidence=min_confidence,
        psm=psm,
        max_results=max_results,
        prefer_active_window=prefer_active_window,
        within_active_window=within_active_window,
        crop_active_window=crop_active_window,
        require_active_title=require_active_title,
        max_window_candidates=max_window_candidates,
        capture_screenshot=capture_screenshot,
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        get_active_window=get_active_window,
        kwin_windows_via_script=kwin_windows_via_script,
        ocr_desktop=ocr_desktop,
        audit_fn=audit_fn,
    )
    if not resolved.get("ok"):
        return resolved
    target_window = resolved.get("target_window") or {}
    best_match = resolved.get("best_match") or {}
    if action == "resolve":
        return resolved
    if action == "focus":
        if dry_run:
            return {**resolved, "dry_run": True, "workflow_action": "focus"}
        result = await focus_window(
            window_id=target_window.get("id") or target_window.get("internal_id"),
            title_contains=str(target_window.get("title", "") or title or query),
            target_title=str(target_window.get("title", "") or ""),
            verify=verify,
            verify_timeout_ms=timeout_ms,
            desktop_exec=desktop_exec,
            detect_env=detect_env,
            get_active_window=get_active_window,
            kwin_focus_window=kwin_focus_window,
        )
        return {**resolved, "workflow_action": "focus", "focus_result": result, "ok": bool(result.get("ok"))}
    if action == "click":
        x, y = _target_point(best_match, target_position, offset_x, offset_y)
        if dry_run:
            return {**resolved, "workflow_action": "click", "dry_run": True, "target": {"x": x, "y": y, "position": target_position, "offset_x": offset_x, "offset_y": offset_y}}
        env = detect_env()
        cmd, click_tool, err = build_click_command(env=env, x=x, y=y, button=button, double=double, activate=activate, has_kdotool=shutil.which("kdotool") is not None)
        if err:
            return {"ok": False, "error": err, "status": 500, **resolved}
        exec_result = await desktop_exec(cmd, timeout=10)
        if not exec_result.get("ok"):
            return {"ok": False, "error": f"Click failed ({click_tool}): {exec_result.get('stderr', exec_result.get('error', ''))}", "status": 500, **resolved}
        return {**resolved, "workflow_action": "click", "click_tool": click_tool, "clicked": True, "target": {"x": x, "y": y, "position": target_position, "offset_x": offset_x, "offset_y": offset_y}}
    if dry_run:
        payload = {**resolved, "workflow_action": action, "dry_run": True}
        if action in PLANNED_ACTIONS:
            preview = plan_window_action_geometry(action, before=target_window, displays=list(resolved.get("displays") or []), target_display=target_display)
            if not preview.get("ok"):
                return {**resolved, **preview, "workflow_action": action}
            payload["planned_geometry"] = {"x": preview["x"], "y": preview["y"], "width": preview["width"], "height": preview["height"]}
            payload["source_display"] = preview.get("source_display")
            payload["target_display"] = preview.get("target_display")
        return payload
    result = await perform_window_action(
        action,
        target_id=str(target_window.get("id") or target_window.get("internal_id") or ""),
        title_contains=str(target_window.get("title", "") or title or query),
        target_title=str(target_window.get("title", "") or ""),
        target_display=target_display,
        verify=verify,
        verify_timeout_ms=timeout_ms,
        desktop_exec=desktop_exec,
        detect_env=detect_env,
        kwin_windows_via_script=kwin_windows_via_script,
    )
    return {**resolved, "workflow_action": action, "window_action_result": result, "ok": bool(result.get("ok"))}


__all__ = ["run_text_action"]
