"""Shared control-lease gate for command and raw-script exec paths."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def control_injection_error(
    *,
    command: str,
    request_id: str,
    control_check: Callable[[], dict[str, Any] | None],
    injection_matcher: Callable[[str], str | None],
) -> dict[str, Any] | None:
    """Return 403 state for full halt, or paused/revoked input injection."""
    control = control_check()
    if not control:
        return None
    if control.get("error") == "agent_halted":
        error = dict(control)
        error.update({"request_id": request_id, "matched": None})
        return error
    matched = injection_matcher(command)
    if not matched:
        return None
    error = dict(control)
    error.update({
        "request_id": request_id,
        "matched": matched,
        "message": (
            "Desktop input injection blocked while control is "
            f"{control.get('status')}. Resume control to inject input."
        ),
    })
    return error


def control_injection_response(
    *,
    ctx: Any,
    request: Any,
    command: str,
    request_id: str,
    event_type: str,
    audit_fields: dict[str, Any] | None = None,
) -> Any | None:
    """Apply the shared gate and emit the common audit/accounting response."""
    error = control_injection_error(
        command=command,
        request_id=request_id,
        control_check=ctx.control_check,
        injection_matcher=ctx.is_input_injection_cmd,
    )
    if error is None:
        return None
    audit = {
        "type": event_type,
        "request_id": request_id,
        "reason": error.get("error"),
        "matched": error["matched"],
        "client": request.remote or "127.0.0.1",
    }
    audit.update(audit_fields or {})
    ctx.audit(audit)
    ctx.record_request(is_error=True, count_request=False)
    return ctx.cors_json_response(error, status=403)
