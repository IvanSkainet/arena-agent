"""The checks every JSON exec request passes before it can run.

`/v1/exec` and `/v1/exec/stream` had the same seven guards written out
twice, differing only in the audit event name. Two copies of a security
preamble is one too many -- a check added to one and missed in the other
is how #93 happened -- and the run of sequential `if`s is what CodeScene
reads as a Bumpy Road in the streaming handler.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.exec.control_gate import control_injection_response
from arena.exec.request_shape import (
    OUTSIDE_ROOT,
    limits_and_env,
    requested_command,
    requested_cwd,
)
from arena.handler_helpers import err_json, parse_json_body
from arena.security_commands import command_allowlist_reason

__all__ = ["AcceptedExecRequest", "accept_exec_request"]


@dataclass(frozen=True)
class AcceptedExecRequest:
    """Everything the handler needs once the request has cleared."""

    request_id: str
    cmd: str
    cwd: Path
    # `int`, matching `limits_and_env` and what `run_shell_command_stream`
    # accepts. Widening it to float here cost a pyrefly bad-argument-type
    # and nothing else -- the value is a whole number of seconds.
    timeout: int
    max_output: int
    env: dict[str, str]


async def accept_exec_request(
    ctx: Any, request: web.Request, cfg: dict, *, event_type: str,
) -> tuple[AcceptedExecRequest | None, web.Response | None]:
    """Return the accepted request, or the refusal to send instead.

    Exactly one of the two is not None. `event_type` names the audit
    event for a refusal, which is the only thing that differed between
    the two copies of this.
    """
    data, jerr = await parse_json_body(request, ctx)
    if jerr is not None:
        ctx.record_request(is_error=True, count_request=False)
        return None, jerr
    assert data is not None  # the guard above already proved this

    request_id = str(data.get("request_id") or uuid.uuid4())

    # Absent, or present and unspawnable: a NUL cannot cross `execve`, and
    # refusing it here rather than at the spawn keeps it out of the audit
    # journal as well as out of the 500s (#288).
    cmd, unusable = requested_command(data)
    if unusable:
        ctx.record_request(is_error=True, count_request=False)
        return None, err_json(ctx, unusable, status=400, request_id=request_id)

    refusal = _policy_refusal(_Subject(
        ctx=ctx, request=request, cfg=cfg, cmd=cmd,
        request_id=request_id, event_type=event_type))
    if refusal is not None:
        return None, refusal

    root: Path = cfg["root"]
    boundary = None if cfg["allow_any_cwd"] else ctx.under_root
    cwd, cwd_error = requested_cwd(data, root, under_root=boundary)
    if cwd_error:
        # 403 when the sandbox says no, 400 when the path itself is
        # unusable -- the same split `_cwd_refusal` makes, kept here so
        # the caller does not have to re-derive it.
        ctx.record_request(is_error=True, count_request=False)
        status = 403 if cwd_error.startswith(OUTSIDE_ROOT) else 400
        return None, err_json(ctx, cwd_error, status=status,
                              request_id=request_id)
    assert cwd is not None  # pyrefly: the error branch returned already

    timeout, max_output, env = limits_and_env(data, cfg, ctx)
    return AcceptedExecRequest(
        request_id=request_id, cmd=cmd, cwd=cwd, timeout=timeout,
        max_output=max_output, env=env), None


@dataclass(frozen=True)
class _Subject:
    """One command under judgement, with everything needed to judge it.

    A parameter object rather than six arguments: the gates each need a
    different subset, and threading all six through every one of them is
    what CodeScene flags as an Excess Number of Function Arguments.
    """

    ctx: Any
    request: web.Request
    cfg: dict
    cmd: str
    request_id: str
    event_type: str

    def refuse(self, reason: str, *, client: str) -> web.Response:
        """Audit a 403 and build it."""
        self.ctx.audit({"type": self.event_type, "request_id": self.request_id,
                        "cmd": self.cmd, "reason": reason, "client": client})
        self.ctx.record_request(is_error=True, count_request=False)
        return err_json(self.ctx, reason, status=403,
                        request_id=self.request_id)


def _policy_refusal(subject: _Subject) -> web.Response | None:
    """The three policy gates: blocklist, control characters, profile."""
    ctx, request = subject.ctx, subject.request

    reason = ctx.blocked_reason(subject.cmd)
    if reason:
        return subject.refuse(reason, client=request.remote or "127.0.0.1")

    blocked = control_injection_response(
        ctx=ctx, request=request, command=subject.cmd,
        request_id=subject.request_id,
        event_type=f"{subject.event_type}_control",
        audit_fields={"cmd": subject.cmd},
    )
    if blocked is not None:
        return blocked

    if subject.cfg["profile"] != "cautious":
        return None
    reason = command_allowlist_reason(
        subject.cmd, ctx.first_word(subject.cmd), ctx.cautious_allow)
    if not reason:
        return None
    return subject.refuse(f"{reason}; use --profile owner-shell",
                          client=request.remote or "local-client")
