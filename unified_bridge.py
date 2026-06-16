#!/usr/bin/env python3
"""Arena Unified Bridge compatibility entrypoint.

The bridge implementation is modular and lives under ``arena/``.  This file is
kept intentionally thin so old commands and imports continue to work:

- ``python unified_bridge.py serve`` / ``token`` / CLI dispatch;
- historical ``import unified_bridge as ub`` helper and handler globals;
- Windows ``pythonw.exe`` stdio/resource compatibility bootstrap.

New code should be added to focused ``arena/<domain>/`` modules, not here.
"""
from __future__ import annotations

import sys
import os

# --- Windows pythonw.exe stdout/stderr fix ---
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# --- Windows resource module mock ---
if sys.platform == "win32":
    class MockResource:
        RLIMIT_NOFILE = 0
        def getrlimit(self, *a, **kw): return (1024, 1024)
        def setrlimit(self, *a, **kw): pass
    sys.modules["resource"] = MockResource()
    import resource  # noqa: E402

import arena.runtime_deps as _runtime_deps  # noqa: E402
from arena.runtime.namespace import apply_compat_exports, build_runtime_namespace  # noqa: E402
from arena.wiring.bridge_runtime import build_bridge_runtime  # noqa: E402


_runtime_namespace = build_runtime_namespace(_runtime_deps)
_bridge_runtime = build_bridge_runtime(_runtime_namespace)
apply_compat_exports(globals(), _runtime_namespace, _bridge_runtime)

Path = _runtime_namespace["Path"]
Any = _runtime_namespace["Any"]
argparse = _runtime_namespace["argparse"]
_resolve_token_runtime = _runtime_namespace["_resolve_token_runtime"]
TOKEN_FILE = _runtime_namespace["TOKEN_FILE"]
b64_token = _runtime_namespace["b64_token"]
log = _runtime_namespace["log"]
_daemonize_runtime = _runtime_namespace["_daemonize_runtime"]
CliContext = _runtime_namespace["CliContext"]
VERSION = _runtime_namespace["VERSION"]
AUDIT = _runtime_namespace["AUDIT"]
DEFAULT_MAX_OUTPUT = _runtime_namespace["DEFAULT_MAX_OUTPUT"]
DEFAULT_MAX_CONCURRENT = _runtime_namespace["DEFAULT_MAX_CONCURRENT"]
_cdp_state = _runtime_namespace["_cdp_state"]
_runtime_make_app = _bridge_runtime["make_app"]
_runtime_hardware_from_inventory_sync = _bridge_runtime["_hardware_from_inventory_sync"]
_runtime_skill_install_sync = _bridge_runtime["_skill_install_sync"]
_ensure_session_env = _bridge_runtime["_ensure_session_env"]
_load_config_file = _bridge_runtime["_load_config_file"]
_rotate_all_logs_on_startup = _bridge_runtime["_rotate_all_logs_on_startup"]
_signal_handler = _bridge_runtime["_signal_handler"]
_cli_serve = _runtime_namespace["_cli_serve"]
_cli_token_cmd = _runtime_namespace["_cli_token_cmd"]
_cli_main = _runtime_namespace["_cli_main"]


def make_app(cfg: dict):
    """Facade app factory that mirrors runtime app ref into compatibility globals."""
    app = _runtime_make_app(cfg)
    globals()["_app_ref"] = _runtime_namespace.get("_app_ref")
    return app


def _hardware_from_inventory_sync(timeout: int = 45) -> dict[str, Any]:
    """Compatibility wrapper that honors facade-level monkeypatches."""
    _runtime_namespace["_inventory_sync"] = globals().get("_inventory_sync", _runtime_namespace["_inventory_sync"])
    _runtime_namespace["_hwinfo_sync"] = globals().get("_hwinfo_sync", _runtime_namespace["_hwinfo_sync"])
    return _runtime_hardware_from_inventory_sync(timeout)


globals()["_hardware_from_inventory_sync"] = _hardware_from_inventory_sync


def _skill_install_sync(name: str, url: str) -> dict[str, Any]:
    """Compatibility wrapper that honors facade-level SKILLS_DIR monkeypatches."""
    _runtime_namespace["SKILLS_DIR"] = globals().get("SKILLS_DIR", _runtime_namespace["SKILLS_DIR"])
    return _runtime_skill_install_sync(name, url)


_skill_install_sync.__module__ = "arena.skills.runtime"
globals()["_skill_install_sync"] = _skill_install_sync

def resolve_token(cli_token: str | None) -> tuple[str, Path]:
    return _resolve_token_runtime(
        cli_token,
        default_token_file=TOKEN_FILE,
        token_generator=b64_token,
        log_info=log.info,
    )


def _daemonize() -> None:
    return _daemonize_runtime(log_error=log.error)


def _set_rate_limit_config_from_file(rl: dict[str, Any]) -> None:
    global _rate_limit_max, _rate_limit_window
    if rl.get("max_requests"):
        _rate_limit_max = int(rl["max_requests"])
    if rl.get("window_seconds"):
        _rate_limit_window = float(rl["window_seconds"])


_cli_ctx = CliContext(
    version=VERSION,
    audit_path=AUDIT,
    default_max_output=DEFAULT_MAX_OUTPUT,
    default_max_concurrent=DEFAULT_MAX_CONCURRENT,
    cdp_state=_cdp_state,
    make_app=make_app,
    resolve_token=resolve_token,
    token_generator=b64_token,
    daemonize=_daemonize,
    ensure_session_env=_ensure_session_env,
    load_config_file=_load_config_file,
    rotate_all_logs_on_startup=_rotate_all_logs_on_startup,
    signal_handler=_signal_handler,
    set_rate_limit_config=_set_rate_limit_config_from_file,
    log_info=log.info,
)


def serve(args: argparse.Namespace) -> None:
    return _cli_serve(args, _cli_ctx)


def token_cmd(args: argparse.Namespace) -> None:
    return _cli_token_cmd(args, _cli_ctx)


def main() -> None:
    return _cli_main(_cli_ctx)


if __name__ == "__main__":
    main()
