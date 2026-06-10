"""Shared handler context objects for modular API handlers."""
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
class ServiceHandlerContext:
    """Dependencies for service/capabilities/restart handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    service_info_sync: Callable[[], dict[str, Any]]
    sys_svc_sync: Callable[[], dict[str, Any]]
    capabilities_sync: Callable[[], dict[str, Any]]
    spawn_respawn_helper: Callable[[int], tuple[bool, str]]
    audit: Callable[[dict[str, Any]], None]
