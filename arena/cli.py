"""Command-line entry points for the Arena bridge."""
from __future__ import annotations

import argparse
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class CliContext:
    version: str
    audit_path: Path
    default_max_output: int
    default_max_concurrent: int
    cdp_state: dict[str, Any]
    make_app: Callable[[dict[str, Any]], web.Application]
    resolve_token: Callable[[str | None], tuple[str, Path]]
    token_generator: Callable[[], str]
    daemonize: Callable[[], None]
    ensure_session_env: Callable[[], None]
    load_config_file: Callable[[], dict[str, Any]]
    rotate_all_logs_on_startup: Callable[[], None]
    signal_handler: Callable[[int, Any], None]
    set_rate_limit_config: Callable[[dict[str, Any]], None]
    log_info: Callable[..., None]


def serve(args: argparse.Namespace, ctx: CliContext) -> None:
    if getattr(args, "background", False) and os.name != "nt":
        ctx.daemonize()

    ctx.ensure_session_env()

    file_cfg = ctx.load_config_file()
    if file_cfg.get("port"):
        args.port = int(file_cfg["port"])
    if file_cfg.get("profile"):
        args.profile = file_cfg["profile"]
    if file_cfg.get("timeout"):
        args.timeout = int(file_cfg["timeout"])
    if file_cfg.get("max_concurrent"):
        args.max_concurrent = int(file_cfg["max_concurrent"])
    if file_cfg.get("bind"):
        args.bind = file_cfg["bind"]

    cdp_cfg = file_cfg.get("cdp", {})
    if cdp_cfg.get("port"):
        ctx.cdp_state["port"] = int(cdp_cfg["port"])
    if cdp_cfg.get("headless") is not None:
        ctx.cdp_state["headless"] = bool(cdp_cfg["headless"])

    if file_cfg.get("rate_limit"):
        ctx.set_rate_limit_config(file_cfg["rate_limit"])

    tf = getattr(args, "token_file", "") or ""
    if tf:
        os.environ["ARENA_TOKEN_FILE"] = tf

    token, token_file_used = ctx.resolve_token(args.token)

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = {
        "token": token,
        "token_file": str(token_file_used),
        "profile": args.profile,
        "root": root,
        "port": args.port,
        "allow_any_cwd": args.allow_any_cwd,
        "timeout": args.timeout,
        "max_timeout": args.max_timeout,
        "max_output": args.max_output,
        "max_concurrent": args.max_concurrent,
        "semaphore": None,
        "active_exec": 0,
    }

    app = ctx.make_app(cfg)

    ctx.rotate_all_logs_on_startup()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, ctx.signal_handler)
        except (OSError, ValueError):
            pass

    # v4.1.0: auto-detect a suitable bind when the operator asks for
    # it (either --bind auto or ARENA_AUTO_BIND=1 in env). When a
    # Tailscale or ZeroTier interface is present we widen to 0.0.0.0
    # so agents on the overlay can actually reach the bridge -- the
    # old default of 127.0.0.1 silently broke that use case.
    from arena.bind_detect import resolve_bind as _resolve_bind
    effective_bind, bind_reason = _resolve_bind(args.bind, log_info=ctx.log_info)
    if effective_bind != args.bind:
        ctx.log_info("[bind] --bind=%r resolved to %s (%s)",
                     args.bind, effective_bind, bind_reason)
    args.bind = effective_bind

    ctx.log_info("Arena Unified Bridge v%s on http://%s:%s", ctx.version, args.bind, args.port)
    ctx.log_info("profile=%s root=%s audit=%s max_concurrent=%s", args.profile, root, ctx.audit_path, args.max_concurrent)
    ctx.log_info("All services multiplexed on single port: bridge, MCP, SSE, WS, gateway, dashboard, task-runner")
    ctx.log_info("Stop with Ctrl+C.")

    web.run_app(app, host=args.bind, port=args.port, print=None, access_log=None)


def token_cmd(_: argparse.Namespace, ctx: CliContext) -> None:
    ctx.log_info("New token: %s", ctx.token_generator())


def build_parser(ctx: CliContext) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Arena Unified Bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("token", help="Generate a strong random token")
    sp.set_defaults(func=lambda args: token_cmd(args, ctx))

    sp = sub.add_parser("serve", help="Run unified bridge")
    sp.add_argument("--bind", default="127.0.0.1",
                    help="Bind address. 'auto' widens to 0.0.0.0 when a "
                         "Tailscale or ZeroTier interface is detected "
                         "(v4.1.0). Explicit addresses (e.g. 10.5.1.2 or "
                         "0.0.0.0) are honoured verbatim. Default is "
                         "127.0.0.1; export ARENA_AUTO_BIND=1 to get the "
                         "auto behaviour without changing the flag.")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--token")
    sp.add_argument("--token-file", dest="token_file", default="",
                    help="Path to token file (default: ~/arena-bridge/token.txt)")
    sp.add_argument("--root", default=str(Path.home()))
    sp.add_argument("--allow-any-cwd", action="store_true")
    sp.add_argument("--profile", choices=["cautious", "owner-shell"], default="cautious")
    sp.add_argument("--timeout", type=int, default=60)
    sp.add_argument("--max-timeout", type=int, default=600)
    sp.add_argument("--max-output", type=int, default=ctx.default_max_output)
    sp.add_argument("--max-concurrent", type=int, default=ctx.default_max_concurrent)
    sp.add_argument("--background", action="store_true", help="Daemonize on Linux (fork + detach)")
    sp.set_defaults(func=lambda args: serve(args, ctx))
    return p


def main(ctx: CliContext, argv: list[str] | None = None) -> None:
    parser = build_parser(ctx)
    args = parser.parse_args(argv)
    args.func(args)
