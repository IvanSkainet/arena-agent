"""Shared aiohttp AppKey definitions for bridge application state."""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

APP_CFG = web.AppKey("cfg", dict[str, Any])
APP_MCP_SESSIONS = web.AppKey("mcp_sessions", dict[str, Any])
# #211: serialises `POST /v1/token/regenerate`. The write runs in an
# eight-worker executor, so without it two overlapping requests can leave
# `cfg["token"]` and the token file holding different values -- the exact
# disk/memory divergence that locks every client out after a restart.
APP_TOKEN_ROTATION_LOCK = web.AppKey("token_rotation_lock", asyncio.Lock)
# These four hold the background loops, every one created with
# `asyncio.ensure_future(...)` in arena/lifecycle.py. Declaring them `Any`
# meant `await tr` in on_cleanup read as awaiting Any, hiding whether the
# shutdown path was awaiting a real task at all.
APP_TASK_RUNNER = web.AppKey("task_runner", asyncio.Task)
APP_LOG_CLEANUP = web.AppKey("log_cleanup", asyncio.Task)
APP_FILE_WATCH_LOOP = web.AppKey("file_watch_loop", asyncio.Task)
APP_MISSION_SCHEDULE_LOOP = web.AppKey("mission_schedule_loop", asyncio.Task)

__all__ = [
    "APP_CFG",
    "APP_MCP_SESSIONS",
    "APP_TOKEN_ROTATION_LOCK",
    "APP_TASK_RUNNER",
    "APP_LOG_CLEANUP",
    "APP_FILE_WATCH_LOOP",
    "APP_MISSION_SCHEDULE_LOOP",
]
