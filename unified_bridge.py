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
import sqlite3

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

from arena.legacy_imports import *  # noqa: F401,F403,E402


_legacy_bridge_runtime = build_legacy_bridge_runtime(globals())
globals().update(_legacy_bridge_runtime)


# ============================================================================
# MAIN
# ============================================================================

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
