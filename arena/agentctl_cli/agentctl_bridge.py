"""agentctl bridge commands (v4.22.0).

Client-side URL discovery and connectivity probing over the
v4.1.0 ``/v1/agent/config`` endpoint. Complements the server-side
tunnels probe by measuring latency *from the caller's* vantage
point, which can differ dramatically from the bridge's own view
(e.g. a sandboxed agent may reach ZeroTier faster than Tailscale
even when both are green on the server side).

Verbs::

    agentctl bridge urls              # list every reachable URL
    agentctl bridge urls --json       # raw agent/config JSON
    agentctl bridge best              # print the fastest URL from
                                      # this vantage (one line, script-friendly)
    agentctl bridge best --json       # {"provider":..,"url":..,"latency_ms":..}
    agentctl bridge test              # probe every URL, print a table
    agentctl bridge test --json       # emit probe results as JSON
    agentctl bridge help              # per-verb usage

Environment / config precedence for the discovery endpoint itself:
the CLI uses ``ARENA_BRIDGE_URL`` / token exactly like every other
agentctl verb — that URL is only the *bootstrap* channel. Once
``/v1/agent/config`` responds, the returned URL list is measured
independently, so ``bridge best`` may recommend a URL that is
different from the bootstrap.

Exit codes:
    0  success
    1  bootstrap bridge unreachable / bridge returned ok:false
    2  usage error / unknown verb
    3  ``best`` / ``test`` found zero reachable URLs
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from arena.agentctl_cli.agentctl_common import BRIDGE_TOKEN, bridge_get


_HELP = """Usage: agentctl bridge <verb> [args]

Verbs:
  urls [--json]
      List every reachable URL the bridge is currently advertising
      via /v1/agent/config, in effective priority order (breaker-
      deprioritized providers sink to the tail).

  best [--json] [--timeout SECONDS]
      Probe every advertised URL from this machine and print the
      one with the lowest latency. Exit 3 when nothing responded.
      --timeout   per-URL probe timeout in seconds (default 2.0)

  test [--json] [--timeout SECONDS]
      Same measurement as ``best`` but prints the full table.

  help
      Show this message.

Environment:
  ARENA_BRIDGE_URL     bootstrap channel used to fetch agent/config
  ARENA_BRIDGE_TOKEN   bearer used for the health probes

The probe hits GET /health on every advertised URL with the
same bearer token. Latency is walltime for the full HTTP round
trip, so it includes TLS handshake — that's on purpose because
that is what a real agent pays on every request.
"""


def _ssl_ctx(url: str):
    if not url.startswith("https"):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = 0
    return ctx


def _probe_url(url: str, timeout: float) -> dict[str, Any]:
    """Time a single GET /health against ``url``.

    Returns a dict shaped ``{'url':..,'ok':bool,'latency_ms':float|None,
    'status':int|None,'error':str|None}``.
    """
    full = url.rstrip("/") + "/health"
    req = urllib.request.Request(full)
    if BRIDGE_TOKEN:
        req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
    kwargs: dict[str, Any] = {"timeout": timeout}
    ctx = _ssl_ctx(url)
    if ctx is not None:
        kwargs["context"] = ctx
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, **kwargs) as resp:
            _ = resp.read(64)
            latency = (time.monotonic() - t0) * 1000.0
            return {"url": url, "ok": True, "latency_ms": round(latency, 1),
                    "status": resp.status, "error": None}
    except urllib.error.HTTPError as e:
        latency = (time.monotonic() - t0) * 1000.0
        return {"url": url, "ok": False, "latency_ms": round(latency, 1),
                "status": e.code, "error": f"HTTP {e.code}"}
    except Exception as e:  # timeout, DNS, TLS, refused, ...
        return {"url": url, "ok": False, "latency_ms": None,
                "status": None, "error": type(e).__name__ + ": " + str(e)[:120]}


def _fetch_config() -> dict[str, Any]:
    """Call /v1/agent/config, bailing out with exit 1 on failure."""
    try:
        return bridge_get("/v1/agent/config", timeout=15)
    except Exception as e:
        print(f"ERROR: could not reach /v1/agent/config: {e}", file=sys.stderr)
        sys.exit(1)


def _extract_urls(cfg: dict[str, Any]) -> list[dict[str, str]]:
    urls = cfg.get("urls") or []
    return [u for u in urls if isinstance(u, dict) and u.get("url")]


def urls(args: list[str]) -> None:
    as_json = "--json" in args
    cfg = _fetch_config()
    if as_json:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return
    entries = _extract_urls(cfg)
    if not entries:
        print("(no reachable URLs advertised)")
        sys.exit(3)
    depr = set(cfg.get("deprioritized") or [])
    print(f"Bridge version: {cfg.get('version','?')}")
    print(f"Reachable:      {cfg.get('reachable_count','?')}")
    prio = cfg.get("priority") or []
    print(f"Priority:       {' > '.join(prio) if prio else '(unset)'}")
    print()
    print(f"{'#':>2}  {'provider':<12} {'kind':<10} url")
    print(f"{'-'*2}  {'-'*12} {'-'*10} {'-'*40}")
    for i, u in enumerate(entries, 1):
        prov = u.get("provider") or "?"
        mark = " (deprio)" if prov in depr else ""
        print(f"{i:>2}  {prov:<12} {u.get('kind','?'):<10} {u.get('url')}{mark}")


def _probe_all(cfg: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    """Probe every advertised URL sequentially.

    Sequential (not parallel) on purpose: keeps the code trivially
    portable and avoids opening N sockets against the same bridge
    at once, which some tunnels (cloudflared free-tier especially)
    dislike. Total wall-time is capped at ``timeout * len(urls)``
    which is a couple seconds for the typical 3-URL setup.
    """
    results: list[dict[str, Any]] = []
    for u in _extract_urls(cfg):
        res = _probe_url(u["url"], timeout)
        res["provider"] = u.get("provider")
        res["kind"] = u.get("kind")
        results.append(res)
    return results


def _parse_timeout(args: list[str], default: float = 2.0) -> float:
    if "--timeout" not in args:
        return default
    idx = args.index("--timeout")
    try:
        return float(args[idx + 1])
    except (IndexError, ValueError):
        print("ERROR: --timeout requires a numeric argument (seconds).",
              file=sys.stderr)
        sys.exit(2)


def best(args: list[str]) -> None:
    as_json = "--json" in args
    timeout = _parse_timeout(args)
    cfg = _fetch_config()
    results = _probe_all(cfg, timeout)
    ok = [r for r in results if r.get("ok") and r.get("latency_ms") is not None]
    if not ok:
        if as_json:
            print(json.dumps({"ok": False, "error": "no reachable URLs",
                              "results": results}, indent=2))
        else:
            print("ERROR: no advertised URL is reachable from this machine",
                  file=sys.stderr)
        sys.exit(3)
    ok.sort(key=lambda r: r["latency_ms"])
    winner = ok[0]
    if as_json:
        print(json.dumps({"ok": True, "provider": winner["provider"],
                          "url": winner["url"], "kind": winner["kind"],
                          "latency_ms": winner["latency_ms"],
                          "considered": len(results)}, indent=2))
    else:
        print(winner["url"])


def test(args: list[str]) -> None:
    as_json = "--json" in args
    timeout = _parse_timeout(args)
    cfg = _fetch_config()
    results = _probe_all(cfg, timeout)
    if as_json:
        print(json.dumps({"ok": any(r.get("ok") for r in results),
                          "results": results}, indent=2))
        if not any(r.get("ok") for r in results):
            sys.exit(3)
        return
    print(f"{'provider':<12} {'kind':<10} {'ok':<4} {'lat(ms)':>8}  url  (error)")
    print(f"{'-'*12} {'-'*10} {'-'*4} {'-'*8}  {'-'*40}")
    any_ok = False
    for r in results:
        lat = r.get("latency_ms")
        lat_s = f"{lat:>8.1f}" if lat is not None else "     n/a"
        ok = "yes" if r.get("ok") else "no"
        if r.get("ok"):
            any_ok = True
        tail = r.get("url", "?")
        if r.get("error"):
            tail = f"{tail}  ({r['error']})"
        print(f"{r.get('provider','?'):<12} {r.get('kind','?'):<10} "
              f"{ok:<4} {lat_s}  {tail}")
    if not any_ok:
        sys.exit(3)


def help_(args: list[str]) -> None:
    print(_HELP)


DISPATCH = {
    "urls": urls,
    "best": best,
    "test": test,
    "help": help_,
    "": urls,
}
