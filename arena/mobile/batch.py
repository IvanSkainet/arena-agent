"""Batch action executor.

An agent typically wants a sequence of actions applied to the same
device — "tap here, wait 500ms, type 'foo', press Enter, screenshot".
Doing that as five separate HTTP round-trips over Tailscale wastes
~200 ms per hop and forces the agent to re-authenticate every call.

`POST /v1/mobile/{serial}/batch` takes a JSON array of steps and
executes them serially on the bridge, returning one aggregated
response. On the first failing step the batch aborts (unless
`continue_on_error=True` is set on the step) and the remaining steps
are reported as `skipped`.

Every step is dispatched through the *existing* per-action functions
(arena.mobile.input.tap, gestures.perform, etc.) so the validation
and audit surfaces stay identical to individual calls.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from arena.mobile import gestures as _gestures
from arena.mobile import helpers as _helpers
from arena.mobile import input as _input
from arena.mobile import shell as _shell
from arena.mobile import ui as _ui

# Step-type registry: type -> (fn, arg extractors). We deliberately do
# NOT expose /apk/install, /helpers/install, /pair, /connect, /disconnect
# here — those are non-idempotent configuration changes that should
# never be quietly issued as part of an agent action loop.
_STEP_HANDLERS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {}


def _register(name: str):
    def deco(fn):
        _STEP_HANDLERS[name] = fn
        return fn
    return deco


@_register("tap")
def _step_tap(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.tap(serial, step.get("x"), step.get("y"))


@_register("swipe")
def _step_swipe(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.swipe(
        serial,
        step.get("x1"), step.get("y1"),
        step.get("x2"), step.get("y2"),
        duration_ms=step.get("duration_ms", 300),
    )


@_register("scroll")
def _step_scroll(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.scroll(
        serial, step.get("x"), step.get("y"),
        vscroll=step.get("vscroll", 0),
        hscroll=step.get("hscroll", 0),
    )


@_register("key")
def _step_key(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.key(serial, step.get("key", ""))


@_register("key_combo")
def _step_key_combo(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.key_combo(serial, step.get("keys") or [])


@_register("type")
def _step_type(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _input.type_text(serial, step.get("text", ""))


@_register("paste")
def _step_paste(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _helpers.paste_text(serial, step.get("text", ""))


@_register("gesture")
def _step_gesture(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _gestures.perform(serial, step.get("gesture", ""))


@_register("shell")
def _step_shell(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _shell.restricted_shell(serial, step.get("command", ""))


@_register("tap_by")
def _step_tap_by(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    return _ui.tap_by(
        serial,
        id=step.get("id"),
        text=step.get("text"),
        desc=step.get("desc"),
        class_name=step.get("class_name") or step.get("class"),
        package=step.get("package"),
        index=step.get("index"),
        match=step.get("match", "exact"),
    )


@_register("sleep")
def _step_sleep(serial: str, step: dict[str, Any]) -> dict[str, Any]:
    """No-op step that just blocks `duration_ms` — useful for waiting
    on an app transition mid-batch (e.g. tap Login, sleep 800ms,
    screenshot). Guarded to at most 10 seconds so a runaway batch
    can't hold up the aiohttp worker."""
    ms = step.get("duration_ms")
    if not isinstance(ms, (int, float)):
        return {"ok": False, "action": "sleep",
                "error": "sleep requires duration_ms"}
    if ms < 0 or ms > 10_000:
        return {"ok": False, "action": "sleep",
                "error": f"sleep duration_ms out of range 0..10000: {ms}"}
    time.sleep(ms / 1000.0)
    return {"ok": True, "action": "sleep", "duration_ms": ms}


ALLOWED_TYPES = frozenset(_STEP_HANDLERS.keys())


def run_batch(
    serial: str,
    steps: list[dict[str, Any]],
    *,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Run steps sequentially and return an aggregated report.

    Args:
      serial: adb device serial (same as every other /v1/mobile route).
      steps: list of `{"type": ..., ...step-specific fields}` dicts.
      stop_on_error: when True (default) the batch aborts on the first
        failing step; when False, every step runs and the report tells
        you which ones failed. Per-step `continue_on_error: true` also
        works when the top-level flag is on default.

    Response:
      {"ok": bool,   # True iff every non-skipped step reported ok
       "serial": str,
       "step_count": int,
       "executed": int,
       "results": [ {index, type, ok, duration_ms, ..., skipped?} ],
       "total_duration_ms": int,
       "error": str | None}
    """
    if not isinstance(serial, str) or not serial.strip():
        return {"ok": False, "error": "serial required"}
    if not isinstance(steps, list):
        return {"ok": False, "error": "steps must be a list"}
    if len(steps) == 0:
        return {"ok": False, "error": "steps list is empty"}
    if len(steps) > 100:
        return {"ok": False, "error": f"too many steps ({len(steps)}; max 100)",
                "hint": "Batch is capped at 100 to keep any single "
                        "request under the aiohttp read timeout."}

    # Validate every step's type up front so we don't half-execute a
    # batch that was going to fail on step 47.
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            return {"ok": False,
                    "error": f"step {idx}: must be an object, got {type(step).__name__}"}
        stype = step.get("type")
        if stype not in _STEP_HANDLERS:
            return {
                "ok": False,
                "error": f"step {idx}: unknown type {stype!r}",
                "hint": f"Allowed types: {sorted(ALLOWED_TYPES)}",
            }

    started = time.monotonic()
    results: list[dict[str, Any]] = []
    executed = 0
    for idx, step in enumerate(steps):
        stype = step["type"]
        handler = _STEP_HANDLERS[stype]
        step_started = time.monotonic()
        try:
            res = handler(serial, step)
        except Exception as e:
            res = {"ok": False, "action": stype, "error": f"handler crashed: {e}"}
        step_ms = int((time.monotonic() - step_started) * 1000)
        entry = {
            "index": idx,
            "type": stype,
            "ok": bool(res.get("ok")),
            "duration_ms": step_ms,
            "result": res,
        }
        results.append(entry)
        executed += 1
        if not entry["ok"]:
            allow_continue = step.get("continue_on_error", not stop_on_error)
            if not allow_continue:
                # Fill in the remainder as skipped so the caller sees
                # what didn't happen.
                for tail_idx in range(idx + 1, len(steps)):
                    results.append({
                        "index": tail_idx,
                        "type": steps[tail_idx].get("type"),
                        "ok": False,
                        "skipped": True,
                        "duration_ms": 0,
                    })
                break

    total_ms = int((time.monotonic() - started) * 1000)
    all_ok = all(r.get("ok") for r in results if not r.get("skipped"))
    return {
        "ok": all_ok,
        "serial": serial,
        "step_count": len(steps),
        "executed": executed,
        "results": results,
        "total_duration_ms": total_ms,
    }
