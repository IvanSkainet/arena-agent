"""Log rotation and disk-safety background runtime."""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class LogCleanupContext:
    app_dir: Path
    log_files: list[Path]
    max_log_size: int = 10 * 1024 * 1024
    max_log_backups: int = 3
    log_info: Callable[..., None] = lambda *args, **kwargs: None
    log_warning: Callable[..., None] = lambda *args, **kwargs: None
    log_critical: Callable[..., None] = lambda *args, **kwargs: None
    log_error: Callable[..., None] = lambda *args, **kwargs: None


@dataclass(frozen=True)
class LogCleanupRuntime:
    rotate_file_if_oversized: Callable[..., bool]
    rotate_all_logs_on_startup: Callable[[], None]
    check_disk_space: Callable[[], float]
    log_cleanup_loop: Callable[[web.Application], Any]


def rotate_file_if_oversized(path: Path, max_bytes: int, backups: int) -> bool:
    """Rotate a log file if it exceeds max_bytes. Returns True if rotated."""
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
        for i in range(backups, 0, -1):
            old = Path(f"{path}.{i}")
            if old.exists():
                if i == backups:
                    old.unlink()
                else:
                    try:
                        old.rename(Path(f"{path}.{i + 1}"))
                    except OSError:
                        pass
        try:
            path.rename(Path(f"{path}.1"))
        except OSError:
            pass
        return True
    except Exception:
        return False


def make_log_cleanup_runtime(ctx: LogCleanupContext) -> LogCleanupRuntime:
    def _rotate_file_if_oversized(
        path: Path,
        max_bytes: int = ctx.max_log_size,
        backups: int = ctx.max_log_backups,
    ) -> bool:
        return rotate_file_if_oversized(path, max_bytes=max_bytes, backups=backups)

    def _rotate_all_logs_on_startup() -> None:
        """Rotate any oversized log files at bridge startup."""
        rotated = []
        for lf in ctx.log_files:
            if _rotate_file_if_oversized(lf):
                rotated.append(lf.name)
        for name in ("ArenaUnifiedBridge.log", "bridge_err.log"):
            for parent in (
                Path.home() / "arena-agent" / "logs",
                Path.home() / "arena-bridge" / "logs",
                ctx.app_dir / "logs",
            ):
                lf = parent / name
                if _rotate_file_if_oversized(lf, max_bytes=ctx.max_log_size, backups=2):
                    rotated.append(f"{parent.name}/{name}")
        if rotated:
            ctx.log_warning("[LogRotation] Rotated oversized log files at startup: %s", ", ".join(rotated))

    def _check_disk_space() -> float:
        """Return disk usage percentage for the partition containing app_dir."""
        try:
            if sys.platform == "win32":
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    str(ctx.app_dir.drive), None, ctypes.pointer(total_bytes), ctypes.pointer(free_bytes)
                )
                if total_bytes.value > 0:
                    return round((1 - free_bytes.value / total_bytes.value) * 100, 1)
            else:
                stat = os.statvfs(str(ctx.app_dir.parent))
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bavail * stat.f_frsize
                if total > 0:
                    return round((1 - free / total) * 100, 1)
        except Exception:
            pass
        return -1

    async def _log_cleanup_loop(app: web.Application) -> None:
        """Periodic background task: rotate oversized logs and warn on disk space."""
        _rotate_all_logs_on_startup()
        while True:
            try:
                await asyncio.sleep(1800)
                rotated = []
                for lf in ctx.log_files:
                    if _rotate_file_if_oversized(lf):
                        rotated.append(lf.name)
                if rotated:
                    ctx.log_info("[LogCleanup] Rotated: %s", ", ".join(rotated))
                pct = _check_disk_space()
                if pct >= 0 and pct > 90:
                    ctx.log_critical("[DiskSpace] Disk usage at %.1f%%! Consider cleaning up files.", pct)
                elif pct >= 0 and pct > 80:
                    ctx.log_warning("[DiskSpace] Disk usage at %.1f%%", pct)
            except asyncio.CancelledError:
                break
            except Exception as e:
                ctx.log_error("[LogCleanup] Error: %s", e)

    return LogCleanupRuntime(
        rotate_file_if_oversized=_rotate_file_if_oversized,
        rotate_all_logs_on_startup=_rotate_all_logs_on_startup,
        check_disk_space=_check_disk_space,
        log_cleanup_loop=_log_cleanup_loop,
    )
