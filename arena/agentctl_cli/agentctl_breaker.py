"""agentctl breaker commands (v4.17.0).

Wraps the v4.8.0 circuit breaker, v4.14.0 reset endpoint, and
v4.16.0 breaker_summary shape into three shell-friendly verbs:

    agentctl breaker status              # human-readable snapshot
    agentctl breaker status --json       # raw JSON for scripts
    agentctl breaker deprio              # print deprioritized providers
    agentctl breaker reset               # reset all breakers
    agentctl breaker reset <key>         # reset one keyed record
    agentctl breaker help                # per-verb usage

Exit codes are meaningful:
    0  success (nothing wrong / operation completed)
    1  bridge unreachable / bridge returned ok:false
    2  usage error / unknown verb
    3  at least one breaker is currently open (``status`` only)

Rationale for exit-3: lets a shell one-liner say
    ``agentctl breaker status --quiet || alert``
without parsing JSON. When you don't want that behaviour, use
``--no-fail-open``.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from arena.agentctl_cli.agentctl_common import bridge_get, bridge_post


def _help(prog: str = "agentctl breaker") -> None:
    print(f"""Usage: {prog} <verb> [args]

Verbs:
  status [--json] [--quiet] [--no-fail-open]
      Print the current breaker snapshot from /v1/tunnels/probe.
      --json          emit raw JSON (for scripts)
      --quiet         suppress the human-readable table
      --no-fail-open  never exit 3 even if a breaker is open
      Exit 3 when at least one breaker is open (unless --no-fail-open).

  deprio [--json]
      Print just the list of deprioritized providers from
      /v1/agent/config. One provider per line. Empty output when
      everything is healthy. Exit 3 when the list is non-empty.

  reset [KEY]
      POST /v1/tunnels/probe/reset. Empty KEY resets every record;
      a KEY like 'cloudflared|foo.trycloudflare.com:443' resets
      just that record. Prints ``ok: reset=... cleared=N``.

  help
      This message.
""")


def _fetch_probe() -> dict[str, Any]:
    return bridge_get("/v1/tunnels/probe")


def _fetch_agent_config() -> dict[str, Any]:
    return bridge_get("/v1/agent/config")


def _print_status_table(snapshot: dict[str, dict]) -> None:
    """Human-readable snapshot of the raw breaker payload.
    Compact enough to fit in a terminal, sorted for stable diff."""
    if not snapshot:
        print("(breaker empty -- no probes yet)")
        return
    # Column widths derived from the actual keys so long provider
    # names don't line-wrap weirdly.
    keys = sorted(snapshot.keys())
    kw = max(len(k) for k in keys)
    print(f"{'KEY'.ljust(kw)}  STATE   FAILS  COOLDOWN   LAST ERROR")
    for key in keys:
        rec = snapshot[key] or {}
        state = str(rec.get("state") or "?")
        fails = rec.get("consecutive_failures", 0)
        cd = rec.get("cools_down_in_sec")
        cd_str = f"{cd:>7.1f}s" if isinstance(cd, (int, float)) else "        "
        err = str(rec.get("last_error") or "")
        if len(err) > 40:
            err = err[:37] + "..."
        print(f"{key.ljust(kw)}  {state:<6}  {fails:>5}  {cd_str}  {err}")


def _print_summary_footer(summary: dict[str, Any]) -> None:
    """One-line footer mirroring the v4.16.0 summary shape."""
    parts = [
        f"total={summary.get('total_records', 0)}",
        f"open={summary.get('open_count', 0)}",
        f"warn={summary.get('warn_count', 0)}",
    ]
    if summary.get("open"):
        parts.append("open_providers=" + ",".join(summary["open"]))
    if summary.get("warn"):
        parts.append("warn_providers=" + ",".join(summary["warn"]))
    print("summary: " + " ".join(parts))


def _summarize(snapshot: dict[str, dict]) -> dict[str, Any]:
    """Local mirror of arena.admin.tunnels_breaker.summarize_snapshot
    so the CLI works even against an old bridge that doesn't yet
    embed breaker_summary in /v1/agent/config. Same rules
    (open dominates over warn for same-provider dual endpoints)."""
    open_p: set[str] = set()
    warn_p: set[str] = set()
    ok_p: set[str] = set()
    for key, rec in snapshot.items():
        provider = str(key).split("|", 1)[0]
        state = rec.get("state") if isinstance(rec, dict) else None
        fails = 0
        if isinstance(rec, dict):
            raw = rec.get("consecutive_failures", 0)
            fails = int(raw) if isinstance(raw, int) else 0
        if state == "open":
            open_p.add(provider)
        elif fails > 0:
            warn_p.add(provider)
        else:
            ok_p.add(provider)
    warn_p -= open_p
    ok_p -= open_p
    ok_p -= warn_p
    return {
        "open": sorted(open_p),
        "warn": sorted(warn_p),
        "closed_ok": sorted(ok_p),
        "total_records": len(snapshot),
        "open_count": len(open_p),
        "warn_count": len(warn_p),
    }


def _parse_flags(args: list[str]) -> tuple[dict[str, bool], list[str]]:
    """Tiny argv parser -- extract known --flags, leave positional
    args untouched. Avoids pulling argparse in for two options."""
    flags = {"json": False, "quiet": False, "no_fail_open": False}
    rest: list[str] = []
    for a in args:
        if a == "--json":
            flags["json"] = True
        elif a == "--quiet":
            flags["quiet"] = True
        elif a == "--no-fail-open":
            flags["no_fail_open"] = True
        else:
            rest.append(a)
    return flags, rest


def status(args: list[str]) -> None:
    flags, _rest = _parse_flags(args)
    try:
        probe = _fetch_probe()
    except Exception as e:
        print(f"Error contacting bridge: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(probe, dict) or probe.get("ok") is False:
        print(f"Bridge returned failure: {probe!r}", file=sys.stderr)
        sys.exit(1)

    snapshot = probe.get("breaker") or {}
    summary = _summarize(snapshot)

    if flags["json"]:
        print(json.dumps({"breaker": snapshot, "summary": summary},
                         indent=2, ensure_ascii=False))
    elif not flags["quiet"]:
        _print_status_table(snapshot)
        _print_summary_footer(summary)

    if summary["open_count"] > 0 and not flags["no_fail_open"]:
        sys.exit(3)


def deprio(args: list[str]) -> None:
    flags, _rest = _parse_flags(args)
    try:
        cfg = _fetch_agent_config()
    except Exception as e:
        print(f"Error contacting bridge: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(cfg, dict) or cfg.get("ok") is False:
        print(f"Bridge returned failure: {cfg!r}", file=sys.stderr)
        sys.exit(1)

    # v4.16.0 exposes ``deprioritized`` directly; if we're talking
    # to an older bridge, fall back to breaker_summary.open, and
    # if THAT is missing (v4.15.x and older) synthesize from the
    # /v1/tunnels/probe payload.
    deprio_list = cfg.get("deprioritized")
    if deprio_list is None:
        summary = (cfg.get("breaker_summary") or {})
        if isinstance(summary, dict):
            deprio_list = summary.get("open") or []
        else:
            deprio_list = []
    if not isinstance(deprio_list, list):
        deprio_list = []

    if deprio_list is None or (not deprio_list and not deprio_list):
        deprio_list = []

    # Older bridge -- last resort: probe endpoint.
    if not deprio_list and "breaker_summary" not in cfg:
        try:
            probe = _fetch_probe()
            snapshot = probe.get("breaker") or {}
            deprio_list = _summarize(snapshot)["open"]
        except Exception:
            deprio_list = []

    if flags["json"]:
        print(json.dumps({"deprioritized": deprio_list},
                         ensure_ascii=False))
    else:
        for name in deprio_list:
            print(name)

    if deprio_list:
        sys.exit(3)


def reset(args: list[str]) -> None:
    key = args[0] if args else None
    payload: dict = {"key": key} if key else {}
    try:
        r = bridge_post("/v1/tunnels/probe/reset", payload)
    except Exception as e:
        print(f"Error contacting bridge: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(r, dict) or r.get("ok") is False:
        print(f"Reset failed: {r!r}", file=sys.stderr)
        sys.exit(1)
    print(f"ok: reset={r.get('reset', '?')} cleared={r.get('keys_cleared', 0)}")


def help_(args: list[str]) -> None:
    _help()


__all__ = ["status", "deprio", "reset", "help_"]
