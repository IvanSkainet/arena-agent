"""Resolve filesystem context values only after live configuration is published."""
from __future__ import annotations

from pathlib import Path
from typing import cast

from arena.handler_context import FileHandlerContext


def file_home(ctx: FileHandlerContext) -> Path:
    return cast(Path, ctx.home() if callable(ctx.home) else ctx.home)
