"""Cluster/high-availability runtime state and helpers."""
from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import Any, Callable

import aiohttp

CLUSTER_CONFIG: dict[str, Any] = {
    "enabled": False,
    "node_id": "",
    "nodes": [],       # [{"id": "...", "url": "http://...", "role": "leader|follower"}]
    "leader_id": "",
    "heartbeat_interval_s": 10,
    "failover_timeout_s": 30,
}
CLUSTER_STATE: dict[str, Any] = {
    "last_heartbeat": 0.0,
    "role": "standalone",  # standalone | leader | follower
    "peers_healthy": {},
}
_CLUSTER_TASK: asyncio.Task | None = None


def get_node_id() -> str:
    """Generate a unique node ID based on hostname and process id."""
    return f"{socket.gethostname()}-{os.getpid()}"


async def cluster_heartbeat_loop(*, log_error: Callable[..., None] | None = None) -> None:
    """Periodically send heartbeats to peer nodes."""
    while True:
        try:
            await asyncio.sleep(CLUSTER_CONFIG["heartbeat_interval_s"])
            CLUSTER_STATE["last_heartbeat"] = time.time()

            # Check peer health.
            for node in CLUSTER_CONFIG["nodes"]:
                node_url = node.get("url", "")
                if not node_url:
                    continue
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{node_url}/health",
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as resp:
                            healthy = resp.status == 200
                            CLUSTER_STATE["peers_healthy"][node.get("id", node_url)] = {
                                "healthy": healthy,
                                "last_check": time.time(),
                            }
                except Exception:
                    CLUSTER_STATE["peers_healthy"][node.get("id", node_url)] = {
                        "healthy": False,
                        "last_check": time.time(),
                    }

            # Prune stale peer entries (nodes no longer in config).
            known_ids = {n.get("id", n.get("url", "")) for n in CLUSTER_CONFIG["nodes"]}
            CLUSTER_STATE["peers_healthy"] = {
                k: v for k, v in CLUSTER_STATE["peers_healthy"].items() if k in known_ids
            }

            # Simple leader election: node with lowest ID is leader.
            if CLUSTER_CONFIG["nodes"]:
                all_ids = sorted([CLUSTER_CONFIG["node_id"]] + [n.get("id", "") for n in CLUSTER_CONFIG["nodes"]])
                CLUSTER_CONFIG["leader_id"] = all_ids[0]
                CLUSTER_STATE["role"] = "leader" if CLUSTER_CONFIG["leader_id"] == CLUSTER_CONFIG["node_id"] else "follower"

        except asyncio.CancelledError:
            break
        except Exception as e:
            if log_error:
                log_error("[Cluster] Heartbeat error: %s", e)
            await asyncio.sleep(5)


def start_cluster_heartbeat(*, log_error: Callable[..., None] | None = None) -> asyncio.Task:
    """Start/restart the cluster heartbeat task and return it."""
    global _CLUSTER_TASK
    if _CLUSTER_TASK and not _CLUSTER_TASK.done():
        _CLUSTER_TASK.cancel()
    _CLUSTER_TASK = asyncio.create_task(cluster_heartbeat_loop(log_error=log_error))
    return _CLUSTER_TASK


async def stop_cluster_heartbeat() -> None:
    """Stop the cluster heartbeat task if running."""
    global _CLUSTER_TASK
    if _CLUSTER_TASK and not _CLUSTER_TASK.done():
        _CLUSTER_TASK.cancel()
        try:
            await _CLUSTER_TASK
        except asyncio.CancelledError:
            pass
    _CLUSTER_TASK = None
