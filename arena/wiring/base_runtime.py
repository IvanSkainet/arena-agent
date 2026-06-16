"""Base compatibility runtime wiring for unified_bridge."""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any, MutableMapping


def build_base_runtime(g: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build bootstrap wrappers, logging, executors and simple constants."""
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
    return {
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
    }


__all__ = ["build_base_runtime"]
