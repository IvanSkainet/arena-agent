"""CLI extraction tests."""
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.cli import CliContext, build_parser, main, token_cmd  # noqa: E402


def _ctx(events=None):
    events = events if events is not None else []
    return CliContext(
        version="test-version",
        audit_path=Path("audit.jsonl"),
        default_max_output=123,
        default_max_concurrent=4,
        cdp_state={},
        make_app=lambda cfg: web.Application(),
        resolve_token=lambda token: (token or "resolved-token", Path("token.txt")),
        token_generator=lambda: "generated-token",
        daemonize=lambda: events.append("daemonize"),
        ensure_session_env=lambda: events.append("env"),
        load_config_file=lambda: {},
        rotate_all_logs_on_startup=lambda: events.append("rotate"),
        signal_handler=lambda sig, frame: None,
        set_rate_limit_config=lambda cfg: events.append(("rate", cfg)),
        log_info=lambda *args, **kwargs: events.append(("log", args)),
    )


def test_unified_cli_wrappers_bound_to_cli_module():
    assert ub._cli_serve.__module__ == "arena.cli"
    assert ub._cli_token_cmd.__module__ == "arena.cli"
    assert ub._cli_main.__module__ == "arena.cli"


def test_build_parser_defaults():
    parser = build_parser(_ctx())
    args = parser.parse_args(["serve"])
    assert args.port == 8765
    assert args.max_output == 123
    assert args.max_concurrent == 4
    assert callable(args.func)


def test_token_cmd_logs_generated_token():
    events = []
    token_cmd(None, _ctx(events))
    assert any("generated-token" in str(event) for event in events)


def test_main_token_command():
    events = []
    main(_ctx(events), ["token"])
    assert any("generated-token" in str(event) for event in events)
