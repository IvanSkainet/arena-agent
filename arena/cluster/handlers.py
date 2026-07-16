"""Handlers for cluster/high-availability configuration endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.cluster.runtime import CLUSTER_CONFIG, CLUSTER_STATE
from arena.handler_context import ClusterHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class ClusterHandlers:
    cluster: object


def make_cluster_handlers(ctx: ClusterHandlerContext) -> ClusterHandlers:
    @authed(ctx)
    async def handle_v1_cluster(request: web.Request) -> web.Response:
        """GET /v1/cluster — Cluster configuration and status.
        POST /v1/cluster — Configure clustering (add/remove nodes, enable/disable).
        """

        if request.method == "POST":
            try:
                data = await request.json()
                action = data.get("action", "")

                if action == "enable":
                    CLUSTER_CONFIG["enabled"] = True
                    CLUSTER_CONFIG["node_id"] = CLUSTER_CONFIG["node_id"] or ctx.get_node_id()
                    if "nodes" in data:
                        CLUSTER_CONFIG["nodes"] = data["nodes"]
                    if "heartbeat_interval_s" in data:
                        CLUSTER_CONFIG["heartbeat_interval_s"] = max(5, int(data["heartbeat_interval_s"]))
                    # Start heartbeat loop.
                    ctx.start_heartbeat()
                    CLUSTER_STATE["role"] = "leader" if not CLUSTER_CONFIG["nodes"] else "follower"
                    ctx.log_info("[Cluster] Enabled: node_id=%s, peers=%d",
                                 CLUSTER_CONFIG["node_id"], len(CLUSTER_CONFIG["nodes"]))

                elif action == "disable":
                    CLUSTER_CONFIG["enabled"] = False
                    await ctx.stop_heartbeat()
                    CLUSTER_STATE["role"] = "standalone"
                    ctx.log_info("[Cluster] Disabled")

                elif action == "add_node":
                    node_url = data.get("url", "")
                    node_id = data.get("id", node_url)
                    if not node_url:
                        return ctx.cors_json_response({"ok": False, "error": "url is required"}, status=400)
                    # Avoid duplicates.
                    if not any(n.get("id") == node_id for n in CLUSTER_CONFIG["nodes"]):
                        CLUSTER_CONFIG["nodes"].append({"id": node_id, "url": node_url, "role": "follower"})
                    ctx.log_info("[Cluster] Added node: %s", node_id)

                elif action == "remove_node":
                    node_id = data.get("id", "")
                    CLUSTER_CONFIG["nodes"] = [n for n in CLUSTER_CONFIG["nodes"] if n.get("id") != node_id]
                    ctx.log_info("[Cluster] Removed node: %s", node_id)

                else:
                    return ctx.cors_json_response({"ok": False, "error": "action must be enable/disable/add_node/remove_node"}, status=400)

                ctx.audit({"type": "cluster_update", "action": action})
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        return ctx.cors_json_response({
            "ok": True,
            "cluster": {
                "enabled": CLUSTER_CONFIG["enabled"],
                "node_id": CLUSTER_CONFIG["node_id"],
                "nodes": CLUSTER_CONFIG["nodes"],
                "leader_id": CLUSTER_CONFIG["leader_id"],
                "role": CLUSTER_STATE["role"],
                "last_heartbeat": CLUSTER_STATE["last_heartbeat"],
                "peers_healthy": CLUSTER_STATE["peers_healthy"],
                "heartbeat_interval_s": CLUSTER_CONFIG["heartbeat_interval_s"],
            }
        })

    return ClusterHandlers(cluster=handle_v1_cluster)
