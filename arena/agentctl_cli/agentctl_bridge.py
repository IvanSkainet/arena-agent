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
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from arena.agentctl_cli.agentctl_common import (
    BRIDGE_TOKEN,
    BRIDGE_URL,
    bridge_get,
)


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

  cache [show|clear] [--json]
      Inspect or wipe the persistent URL memory (v4.39.0).
      ``show`` (default) prints the last cached snapshot;
      ``clear`` removes the on-disk file. The cache is what
      lets bridge commands keep working when the bootstrap
      URL becomes unreachable (Tailscale outage etc.).

  help
      Show this message.

Environment:
  ARENA_BRIDGE_URL          bootstrap channel used to fetch agent/config
  ARENA_BRIDGE_TOKEN        bearer used for the health probes
  ARENA_BRIDGE_URL_CACHE    set to 0/false/no/off to disable the
                            persistent URL memory entirely
  ARENA_URL_CACHE_PATH      override the cache location (default
                            ~/.arena/last_urls.json)

The probe hits GET /health on every advertised URL with the
same bearer token. Latency is walltime for the full HTTP round
trip, so it includes TLS handshake — that's on purpose because
that is what a real agent pays on every request.

Fallback behaviour (v4.39.0): when the bootstrap URL is
unreachable, agentctl transparently tries the URLs from the
last successful /v1/agent/config response (cached locally).
Which URL served is reported on stderr so scripts consuming
stdout stay clean.
"""


def _ssl_ctx(url: str):
    """v4.41.0: delegate to the shared TLS helper so verify-by-
    default and the ARENA_INSECURE_TLS opt-out live in exactly
    one place (``arena/agentctl_cli/tls.py``). The pre-v4.41.0
    body did ``check_hostname=False`` + ``verify_mode=0`` on
    every https URL — MITM-open by default.

    Kept as a private wrapper so this module doesn't have to
    grow a new import at every call site."""
    from arena.agentctl_cli.tls import build_ssl_context
    return build_ssl_context(url)


# ---------------------------------------------------------------------------
# v4.41.0: URL redaction for stderr diagnostics
# ---------------------------------------------------------------------------
def _redact_url_for_log(url: str) -> str:
    """Return a version of ``url`` suitable for stderr when the
    consumer is not an interactive TTY.

    Problem statement (audit finding #4): the fallback diagnostic
    line ``NOTE: bootstrap https://cachyos-x8664.tail328f18.ts.net
    unreachable; succeeded via cached URL https://pout-shingle-
    mystify.ngrok-free.dev`` leaks two pieces of infrastructure
    topology into anywhere stderr is captured: CI logs, tmux
    scrollback, shipped bug reports. Tailscale hostnames encode
    the machine name and tailnet id; ngrok reserved domains are
    per-account. Neither is a secret in the "one lookup and
    you're in" sense but both are useful for an attacker
    picking targets.

    Redaction policy:

    * ``isatty()`` on stderr — leave the URL intact. An operator
      staring at their own terminal already knows their
      infrastructure; hiding it would just be annoying.
    * Not a TTY (CI, redirected to file, piped to another
      process) — replace the netloc with ``<scheme>://<8-char-
      prefix>...<tld>``. Preserves enough for humans to
      distinguish "the cloudflared URL" from "the ngrok URL" at
      a glance, but strips the fingerprintable part.
    * Localhost, RFC1918 addresses, and short hostnames (< 12
      chars) are passed through unchanged — nothing sensitive
      to redact.

    A future flag ``ARENA_AGENTCTL_LOG_FULL_URLS=1`` overrides
    the redaction for the "I really need the whole URL in this
    log" case; kept undocumented in --help for now (documented
    inline in the docstring is enough).
    """
    if os.environ.get("ARENA_AGENTCTL_LOG_FULL_URLS", "").strip().lower() in (
            "1", "true", "yes", "on"):
        return url
    try:
        if sys.stderr.isatty():
            return url
    except Exception:
        # e.g. stderr replaced by a StringIO in a test harness --
        # treat as non-TTY.
        pass
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
    except Exception:
        return "<redacted>"
    host = parsed.hostname or ""
    # Preserve short / private hosts; they hold no fingerprintable
    # entropy worth hiding.
    if not host or len(host) < 12:
        return url
    if host in ("localhost",) or host.startswith("127.") or host.startswith(
            "10.") or host.startswith("192.168.") or host.startswith(
            "169.254."):
        return url
    # Best-effort tld: the last dotted component; falls back to
    # the empty string when the host isn't dotted.
    parts = host.split(".")
    tld = parts[-1] if len(parts) > 1 else ""
    prefix = host[:8]
    redacted_host = f"{prefix}...{tld}" if tld else f"{prefix}..."
    netloc = redacted_host
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "",
                       parsed.params or "", parsed.query or "",
                       parsed.fragment or ""))


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


def _fetch_config_from(url: str) -> dict[str, Any]:
    """Low-level: fetch ``/v1/agent/config`` from a specific
    bootstrap URL.

    Separated out from ``_fetch_config`` so the fallback loop
    (v4.39.0) can try each cached URL as a bootstrap in turn.
    Raises the underlying exception on failure -- the caller
    is expected to catch and try the next candidate. Uses the
    same bearer-auth + SSL context as the module-level
    ``bridge_get`` helper, but is not tied to
    ``BRIDGE_URL``.
    """
    full = url.rstrip("/") + "/v1/agent/config"
    req = urllib.request.Request(full)
    if BRIDGE_TOKEN:
        req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
    kwargs: dict[str, Any] = {"timeout": 15}
    ctx = _ssl_ctx(url)
    if ctx is not None:
        kwargs["context"] = ctx
    with urllib.request.urlopen(req, **kwargs) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_config() -> dict[str, Any]:
    """Call /v1/agent/config, falling back to cached URLs on
    bootstrap failure, bailing out with exit 1 only when
    every option is exhausted.

    v4.39.0: this used to be a one-liner that called
    ``bridge_get`` and exited 1 on any error. That worked
    fine until the bootstrap URL itself became unreachable
    (Tailscale outage, cloudflared domain rotation, laptop
    suspended between sessions), at which point the client
    was cut off even though every previous run had listed
    three-plus working alternatives in the response.

    The new flow:

      1. Try ``BRIDGE_URL`` (the bootstrap) first. On success
         we always persist a fresh cache snapshot before
         returning -- keeps the cache warm even when
         everything's working.
      2. On failure, load the cache and try each URL in it
         as a bootstrap. First one that responds wins; we
         also persist a fresh cache snapshot from the fresh
         response, so a rotated cloudflared URL gets picked
         up automatically.
      3. If cache is disabled, absent, or every cached URL
         also fails: print a diagnostic pointing at the
         underlying error and exit 1 as before.

    Cache misses are silent (a missing cache is just the
    normal state for a first run). When a fallback URL
    actually served, we announce that on stderr so an
    operator debugging a Tailscale outage can see what
    happened -- but only on stderr; stdout stays clean for
    script consumers.
    """
    from arena.agentctl_cli import url_cache

    # Attempt 1: the configured bootstrap URL.
    try:
        cfg = _fetch_config_from(BRIDGE_URL)
        # Persist on success so a future outage has a warm
        # cache to lean on. Save is fail-soft -- filesystem
        # errors are swallowed and never affect this call.
        # v4.40.0: pass the bearer token so the snapshot is
        # HMAC-signed. Without a token we cannot verify the
        # signature on load, so we also cannot write a trusted
        # snapshot -- url_cache.save() will no-op in that case
        # (defence-in-depth against cache-poisoning; see
        # arena/agentctl_cli/url_cache.py docstring).
        url_cache.save(cfg, bootstrap_url=BRIDGE_URL, secret=BRIDGE_TOKEN)
        return cfg
    except Exception as primary_err:
        primary_err_str = f"{type(primary_err).__name__}: {primary_err}"

    # Attempt 2..N: URLs from the cache, in priority order.
    # v4.40.0: fallback_bootstrap_urls verifies the HMAC of the
    # on-disk snapshot against our BRIDGE_TOKEN. A mismatched
    # signature (poisoned cache) returns [] just like an absent
    # cache -- the client then falls through to the "everything
    # unreachable" branch below rather than talking to a URL an
    # attacker chose.
    fallback_urls = url_cache.fallback_bootstrap_urls(secret=BRIDGE_TOKEN)
    for candidate in fallback_urls:
        if candidate == BRIDGE_URL:
            # Already tried above -- don't burn a second timeout
            # on the same URL just because it happens to be in
            # the cache too.
            continue
        try:
            cfg = _fetch_config_from(candidate)
        except Exception:
            continue
        # Report on stderr so scripts consuming stdout stay
        # happy but the operator sees what saved them. v4.41.0:
        # both URLs are routed through _redact_url_for_log so
        # that in CI / captured-stderr contexts the Tailscale
        # hostname and ngrok reserved domain are truncated
        # before hitting anything durable.
        print(
            f"NOTE: bootstrap {_redact_url_for_log(BRIDGE_URL)} "
            f"unreachable ({primary_err_str}); succeeded via "
            f"cached URL {_redact_url_for_log(candidate)}",
            file=sys.stderr,
        )
        # Refresh the cache from this successful response --
        # picks up any rotated URLs (cloudflared, ngrok) so the
        # next run has an updated snapshot to fall back on.
        # v4.40.0: same signed-write discipline as the primary
        # path -- the fresh snapshot inherits the bearer-token
        # signature.
        url_cache.save(cfg, bootstrap_url=candidate, secret=BRIDGE_TOKEN)
        return cfg

    # All options exhausted. Print the original error (that's
    # what most users will need to see) and exit 1 to match
    # pre-v4.39.0 behaviour. v4.41.0: primary_err_str can
    # include the bootstrap URL verbatim (URLError includes it),
    # so route it through the redactor to be safe when stderr
    # is captured.
    print(f"ERROR: could not reach /v1/agent/config "
          f"({_redact_url_for_log(BRIDGE_URL)}): {primary_err_str}",
          file=sys.stderr)
    if fallback_urls:
        print(
            f"       also tried {len(fallback_urls)} cached URL(s), "
            "all unreachable.",
            file=sys.stderr,
        )
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


def cache(args: list[str]) -> None:
    """``agentctl bridge cache [show|clear] [--json]`` -- inspect
    or wipe the persistent URL memory (v4.39.0).

    Two sub-verbs:

    * ``show`` (default) -- print the current cache contents
      as a table, or as raw JSON with ``--json``. Also prints
      the cache path + disabled-state so operators can tell
      apart "no cache yet" from "cache disabled via env var".
    * ``clear`` -- remove the cache file. Idempotent -- no
      error when the file is absent.

    Exit codes:
      0  ``show``: cache present or absent (both are OK states)
      0  ``clear``: whether or not a file was removed
      2  usage error (unknown sub-verb)

    Note: the cache is disabled entirely when
    ``ARENA_BRIDGE_URL_CACHE`` is one of ``0`` / ``false`` /
    ``no`` / ``off``. In that case ``show`` reports the
    disabled state and ``clear`` is a no-op.
    """
    from arena.agentctl_cli import url_cache

    sub = (args[0] if args else "show").lower()
    remaining = args[1:] if args else []

    if sub == "show":
        as_json = "--json" in remaining
        # v4.40.0: pass the bearer token so load() can verify the
        # HMAC signature. Without it the cache is refused as
        # "unsigned/untrusted" -- which is the correct answer, and
        # the CLI reports it as "(no cache)" via the None branch
        # below so operators see immediately when their cache is
        # unusable (e.g. after a token rotation).
        data = url_cache.load(secret=BRIDGE_TOKEN)
        if as_json:
            print(json.dumps({
                "ok": True,
                "path": str(url_cache.cache_path()),
                "disabled": url_cache.is_disabled(),
                "cache": data,
            }, indent=2, ensure_ascii=False))
            return
        print(f"path:     {url_cache.cache_path()}")
        print(f"disabled: {url_cache.is_disabled()}")
        if data is None:
            print("(no cache: bootstrap has never succeeded, "
                  "cache is disabled, or the file was cleared)")
            return
        print(f"saved_at: {data.get('saved_at')} "
              f"(bootstrap was {data.get('bootstrap_url')})")
        print(f"{'#':>2}  {'provider':<12} {'kind':<10} url")
        print(f"{'-'*2}  {'-'*12} {'-'*10} {'-'*40}")
        for i, u in enumerate(data.get("urls") or [], 1):
            print(f"{i:>2}  {(u.get('provider') or '?'):<12} "
                  f"{(u.get('kind') or '?'):<10} {u.get('url')}")
        return

    if sub == "clear":
        removed = url_cache.clear()
        if removed:
            print(f"removed {url_cache.cache_path()}")
        else:
            if url_cache.is_disabled():
                print("cache disabled via env; nothing to clear.")
            else:
                print("no cache file to remove.")
        return

    print(f"ERROR: unknown cache sub-verb {sub!r}. "
          "Expected 'show' or 'clear'.", file=sys.stderr)
    sys.exit(2)


def help_(args: list[str]) -> None:
    print(_HELP)


DISPATCH = {
    "urls": urls,
    "best": best,
    "test": test,
    # v4.39.0: cache inspection + wipe verbs.
    "cache": cache,
    "help": help_,
    "": urls,
}
