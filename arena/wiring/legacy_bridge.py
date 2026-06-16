"""Top-level legacy bridge runtime/wiring orchestration.

This is the transitional composition layer used while ``unified_bridge.py`` is
being reduced to a thin compatibility entrypoint.  It consumes the current
legacy globals mapping and returns the compatibility globals that old imports and
route registration still expect.
"""
from __future__ import annotations

import concurrent.futures
import os
import time
from pathlib import Path
from typing import Any, MutableMapping


def build_legacy_bridge_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build legacy runtime state, wrappers, handlers and lifecycle globals."""
    registry: dict[str, Any] = {}

    def update(values: dict[str, Any]) -> None:
        registry.update(values)
        g.update(values)

    def _ensure_session_env() -> None:
        return g["_ensure_session_env_runtime"]()

    def _load_config_file() -> dict:
        return g["_load_config_file_runtime"](
            log_info=g["log"].info,
            log_debug=g["log"].debug,
            log_warning=g["log"].warning,
        )

    def _get_bridge_port() -> int:
        return g["_get_bridge_port_runtime"]()

    log_file = g["APP_DIR"] / "bridge.log"

    def _setup_logging():
        return g["_setup_logging_runtime"](app_dir=g["APP_DIR"], log_file=log_file)

    log = _setup_logging()
    update({
        "_ensure_session_env": _ensure_session_env,
        "_load_config_file": _load_config_file,
        "_get_bridge_port": _get_bridge_port,
        "LOG_FILE": log_file,
        "_setup_logging": _setup_logging,
        "log": log,
        "_EXECUTOR": concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="bridge_io"),
        "_SLOW_EXECUTOR": concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="bridge_slow"),
        "_app_ref": None,
        "CAUTIOUS_ALLOW": {
            "echo", "pwd", "ls", "dir", "tree", "find", "fd", "rg", "grep", "cat", "type",
            "head", "tail", "wc", "whoami", "hostname", "uname", "ver", "systeminfo",
            "ipconfig", "ifconfig", "ip", "ss", "netstat", "python", "python3", "py",
            "node", "npm", "pnpm", "yarn", "bun", "deno", "uv", "git", "gh", "go",
            "cargo", "rustc", "java", "javac", "mvn", "gradle", "dotnet", "pacman",
            "paru", "yay", "winget", "choco", "scoop", "pip", "pip3", "bash", "sh",
            "zsh", "fish", "pwsh", "powershell", "cmd", "agentctl",
        },
        "HOME": str(Path.home()),
        "BIN": str(g["BRIDGE_DIR"] / "bin"),
    })

    update(g["build_runtime_wrappers"](g))
    update(g["build_observability_runtimes"](g))

    paths = g["ArenaPaths"].from_env(g["BRIDGE_DIR"])
    update({
        "PATHS": paths,
        "ROOT_AGENT": paths.root_agent,
        "QUEUE": paths.queue,
        "INBOX": paths.inbox,
        "RUNNING": paths.running,
        "DONE": paths.done,
        "FAILED": paths.failed,
        "SKILLS_DIR": paths.skills_dir,
        "HOOKS_DIR": paths.hooks_dir,
        "AGENTS_DIR": paths.agents_dir,
        "SUBAGENTS_DIR": paths.subagents_dir,
        "MEMORY_FILE": paths.memory_file,
        "MEMORY_DB": paths.memory_db,
        "MISSIONS_DIR": paths.missions_dir,
        "REPORTS_DIR": paths.reports_dir,
        "WEBHOOKS_FILE": paths.webhooks_file,
    })

    update(g["build_mcp_task_runtimes"](g))
    update({"_shutdown_event": None})
    update(g["build_app_lifecycle"](g))

    users_file = g["APP_DIR"] / "users.json"
    user_store = g["UserStore"](users_file, log_warning=log.warning, log_debug=log.debug)
    auth_runtime_ctx = g["AuthRuntimeContext"](
        user_store=user_store,
        rate_limit_lock=g["_rate_limit_lock"],
        rate_limit_store=g["_rate_limit_store"],
        cors_json_response=g["_cors_json_response"],
        log_warning=log.warning,
        now=time.time,
    )
    auth_runtime = g["make_auth_runtime"](auth_runtime_ctx)
    update({
        "_USERS_FILE": users_file,
        "_user_store": user_store,
        "_auth_runtime_ctx": auth_runtime_ctx,
        "_auth_runtime": auth_runtime,
        "_load_users": auth_runtime.load_users,
        "check_auth_with_role": auth_runtime.check_auth_with_role,
        "check_auth": auth_runtime.check_auth,
        "require_auth": auth_runtime.require_auth,
    })

    update(g["build_early_handler_registries"](g))
    update({
        "_check_internet_sync": g["make_check_internet_sync"](g["check_internet"]),
        "_play_beep_sync": g["make_play_beep_sync"](
            play_beep_fn=g["play_beep"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_sysinfo_cim_sync": g["make_sysinfo_cim_sync"](
            sysinfo_cim_cpu_counts_fn=g["sysinfo_cim_cpu_counts"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_sysinfo_sync": g["make_sysinfo_sync"](
            collect_sysinfo_fn=g["collect_sysinfo"],
            clean_platform_name_fn=g["get_clean_platform_name"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "common_status": g["make_common_status"](
            version=g["VERSION"],
            audit_path=g["AUDIT"],
            clean_platform_name_fn=g["get_clean_platform_name"],
        ),
    })
    update({
        "_doctor_sync": g["make_doctor_sync"](
            run_doctor_fn=g["run_doctor"],
            version=g["VERSION"],
            bridge_dir=g["BRIDGE_DIR"],
            memory_dir=g["MEMORY_FILE"].parent,
            missions_dir=g["MISSIONS_DIR"],
            facts_count_fn=lambda: len(g["_load_facts"]()),
            internet_check_fn=g["_check_internet_sync"],
            home_dir=Path.home(),
        )
    })

    update(g["build_system_public_admin_registries"](g))
    update({
        "_hwinfo_sync": g["make_hwinfo_sync"](
            collect_legacy_hwinfo_fn=g["collect_legacy_hwinfo"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_inventory_sync": g["make_inventory_sync"](
            run_inventory_fn=g["run_inventory"],
            bridge_dir=g["BRIDGE_DIR"],
            root_agent=g["ROOT_AGENT"],
            python_executable=os.sys.executable or "python3",
        ),
    })
    update({
        "_hardware_from_inventory_sync": g["make_hardware_from_inventory_sync"](
            globals_ref=g,
            hardware_from_inventory_result_fn=g["hardware_from_inventory_result"],
        )
    })
    update(g["build_hardware_exec_registries"](g))
    update(g["build_memory_resource_browser_runtimes"](g))
    update({
        "_capabilities_sync": g["make_capabilities_sync"](
            build_capabilities_fn=g["build_capabilities"],
            version=g["VERSION"],
            get_cdp_module=g["_get_cdp_module"],
            cdp_state=g["_cdp_state"],
            detect_desktop_env=g["_detect_desktop_env"],
            service_info_sync=g["_service_info_sync"],
            sys_svc_sync=g["_sys_svc_sync"],
        ),
        "_sys_funnel_sync": g["make_sys_funnel_sync"](
            sys_funnel_status_fn=g["_sys_funnel_status_runtime"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
        "_token_path": g["make_token_path"](default_token_file=g["TOKEN_FILE"]),
        "_token_regen_sync": g["make_token_regen_sync"](
            token_regenerate_fn=g["_token_regenerate_runtime"],
            default_token_file=g["TOKEN_FILE"],
        ),
        "_tailscale_funnel_action_sync": g["make_tailscale_funnel_action_sync"](
            tailscale_funnel_action_fn=g["_tailscale_funnel_action_runtime"],
        ),
        "_cloudflared_funnel_action_sync": g["make_cloudflared_funnel_action_sync"](
            cloudflared_funnel_action_fn=g["_cloudflared_funnel_action_runtime"],
            root_agent=g["ROOT_AGENT"],
            subprocess_kwargs_fn=g["_subprocess_kwargs"],
        ),
    })
    update(g["build_service_browser_registries"](g))
    update(g["build_cdp_registries"](g))
    update(g["build_desktop_registries"](g))
    update(g["build_memory_observability_registries"](g))
    update(g["build_tasks_skills_resources_registries"](g))
    return registry


__all__ = ["build_legacy_bridge_runtime"]
