"""Handler context dataclasses for core domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class HandlerContext:
    """Dependencies injected into extracted aiohttp handlers.

    Keeping these dependencies explicit avoids importing the monolith from
    handler modules and makes future tests/refactors substantially easier.
    """

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    slow_executor: Executor
    inventory_sync: Callable[..., dict[str, Any]]
    hardware_sync: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PublicHandlerContext:
    """Dependencies for public index/health/OpenAPI handlers."""

    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    version: str
    now: Callable[[], float]
    hostname: Callable[[], str]
    bridge_port: Callable[[], int]


@dataclass(frozen=True)
class FileHandlerContext:
    """Dependencies for file upload/download handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    audit: Callable[[dict[str, Any]], None]
    home: Any
    bridge_py: Any


@dataclass(frozen=True)
class ExecHandlerContext:
    """Dependencies for exec/process API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    audit: Callable[[dict[str, Any]], None]
    blocked_reason: Callable[[str], str | None]
    control_check: Callable[[], dict | None]
    is_input_injection_cmd: Callable[[str], str | None]
    first_word: Callable[[str], str]
    under_root: Callable[[Any, Any], bool]
    decode_output: Callable[[bytes], str]
    run_shell_command: Callable[..., Any]
    active_processes: dict[str, dict[str, Any]]
    active_processes_snapshot: Callable[..., list[dict[str, Any]]]
    cautious_allow: set[str]
    default_max_output: int


@dataclass(frozen=True)
class GatewayHandlerContext:
    """Dependencies for Web Gateway handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]
    subprocess_kwargs: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class GuiHandlerContext:
    """Dependencies for dashboard GUI handlers."""

    cors_json_response: Callable[..., web.Response]
    bridge_dir: Any
    version: str

__all__ = ['HandlerContext', 'PublicHandlerContext', 'FileHandlerContext', 'ExecHandlerContext', 'GatewayHandlerContext', 'GuiHandlerContext']
