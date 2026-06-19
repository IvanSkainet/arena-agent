"""Shared aiohttp AppKey definitions for bridge application state."""
from __future__ import annotations

from typing import Any

from aiohttp import web

APP_CFG = web.AppKey("cfg", dict[str, Any])
APP_MCP_SESSIONS = web.AppKey("mcp_sessions", dict[str, Any])
APP_TASK_RUNNER = web.AppKey("task_runner", Any)
APP_LOG_CLEANUP = web.AppKey("log_cleanup", Any)

__all__ = [
    "APP_CFG",
    "APP_MCP_SESSIONS",
    "APP_TASK_RUNNER",
    "APP_LOG_CLEANUP",
]
