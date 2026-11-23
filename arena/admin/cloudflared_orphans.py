"""Stop quick tunnels that an earlier bridge process left pointing at this port (#540)."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

OWNER_ENV = "ARENA_BRIDGE_TUNNEL_OWNER"
SWEEP_ENV = "ARENA_TUNNEL_ORPHAN_SWEEP"
_NAMES = ("cloudflared", "cloudflared.exe")
_OFF = ("0", "false", "no", "off")
_STOP_WAIT_SECONDS = 3.0


def owner_env(port: int) -> dict[str, str]:
    """Return the environment for a tunnel child, marked with the port it serves and the bridge that started it."""
    return {**os.environ, OWNER_ENV: f"{port}:{os.getpid()}"}


def sweep_enabled() -> bool:
    """Return False when the operator switched the sweep off."""
    return os.environ.get(SWEEP_ENV, "").strip().lower() not in _OFF


def _targets_port(proc: Any, port: int) -> bool:
    if (proc.info.get("name") or "").lower() not in _NAMES:
        return False
    cmdline = proc.info.get("cmdline") or []
    return "tunnel" in cmdline and f"http://127.0.0.1:{port}" in cmdline


def _marked_owner(proc: Any, port: int) -> int | None:
    """Return the PID of the bridge that started this tunnel for this port, when the tunnel carries the mark."""
    marked_port, _, owner = proc.environ().get(OWNER_ENV, "").partition(":")
    if marked_port != str(port) or not owner.isdigit():
        return None
    return int(owner)


def _started_by_live_process(proc: Any, starter: int, psutil: Any) -> bool:
    try:
        # A PID that was reused after the tunnel started is not the starter.
        return psutil.Process(starter).create_time() <= proc.create_time()
    except psutil.Error:
        return False


def _is_orphan(proc: Any, port: int, psutil: Any, parent_pid_survives: bool) -> bool:
    try:
        if not _targets_port(proc, port):
            return False
        owner = _marked_owner(proc, port)
        if owner == os.getpid():
            # Same PID, earlier program image: the bridge restarted itself with execv.
            return True
        if owner is None and parent_pid_survives:
            # A tunnel from a bridge older than the mark. Windows keeps the PID of a dead parent;
            # elsewhere the orphan is re-parented and its starter cannot be told.
            owner = proc.ppid()
    except psutil.Error:
        # Gone, or not ours to inspect: leave it alone.
        return False
    if owner is None:
        return False
    return not _started_by_live_process(proc, owner, psutil)


def _signal(procs: list[Any], action: str, psutil: Any) -> list[Any]:
    """Send terminate or kill to each process, wait, and return those still running."""
    for proc in procs:
        try:
            getattr(proc, action)()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=_STOP_WAIT_SECONDS)
    return [proc for proc in alive if _still_runs(proc, psutil)]


def _still_runs(proc: Any, psutil: Any) -> bool:
    try:
        # An orphan that nobody reaps stays in the table as a zombie; it holds no tunnel.
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _stop(procs: list[Any], psutil: Any) -> list[int]:
    alive = _signal(procs, "terminate", psutil)
    if alive:
        alive = _signal(alive, "kill", psutil)
    survivors = {proc.pid for proc in alive}
    return [proc.pid for proc in procs if proc.pid not in survivors]


def _load_psutil() -> Any:
    try:
        import psutil
    except ImportError:
        return None
    return psutil


# ``keep_pid`` is the tunnel this process runs now, if any: every other tunnel marked with this PID predates an execv.
# ``psutil`` and ``parent_pid_survives`` default to the real module and the real platform; tests pass their own.
def sweep_orphaned_tunnels(port: int, *, keep_pid: int | None = None, psutil: Any = None,
                           parent_pid_survives: bool | None = None) -> list[int]:
    """Stop cloudflared quick tunnels for ``port`` whose starting bridge is gone, and return the PIDs stopped."""
    psutil = psutil or _load_psutil()
    if psutil is None or not sweep_enabled():
        return []
    if parent_pid_survives is None:
        parent_pid_survives = sys.platform == "win32"
    candidates = psutil.process_iter(["name", "cmdline"])
    orphans = [proc for proc in candidates if proc.pid != keep_pid and _is_orphan(proc, port, psutil, parent_pid_survives)]
    return _stop(orphans, psutil) if orphans else []


def sweep_and_report(port: int, keep_pid: int | None, log: Callable[..., None], **sweep_options: Any) -> None:
    """Sweep, and say which tunnels were stopped."""
    stopped = sweep_orphaned_tunnels(port, keep_pid=keep_pid, **sweep_options)
    if stopped:
        log("[Cloudflared] stopped %d quick tunnel(s) left by an earlier bridge on port %d: pid %s",
            len(stopped), port, ", ".join(map(str, stopped)))
