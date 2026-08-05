"""Fail-closed guard: every route must demand a token unless allow-listed.

Why this exists
---------------
Authentication in this bridge is enforced *inside* each handler
(``require_auth`` / ``@authed``), not by a middleware. That means a new
handler that simply forgets the call is silently reachable by anyone who can
open the port — and nothing breaks visibly, no test goes red, no scanner
complains. It is a product invariant, not a code pattern, so SAST cannot see
it (verified against the full GitHub security-workflow catalogue; see
docs/github_apps_actions_survey.md).

So we check it by execution: build the real app, walk EVERY route the router
actually registered, call it with no credentials, and require a refusal.

Notes for whoever touches this next
-----------------------------------
* The router reports ~510 routes while grepping ``add_get``/``add_post`` in
  the source finds ~237 — aiohttp adds a HEAD for every GET, and some routes
  are registered through helpers. Always trust the router, never a grep.
* ``arena/public/endpoints.py`` is the API catalogue used for docs. It is NOT
  a list of unauthenticated routes (it contains ``POST /v1/exec``). Do not
  wire it in here; the allow-list below is deliberately separate and explicit.
* Requests are dispatched in-process through the aiohttp stack, so the
  per-IP rate limiter (300/min, hardcoded) never distorts the result. An
  earlier over-the-network probe reported 70 bogus "open" routes purely
  because the limiter answers 429 *before* auth runs.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402

# Routes that answer without credentials BY DESIGN. Each entry states why.
# Adding a route here is a deliberate, reviewable decision: it declares that
# the endpoint exposes nothing an unauthenticated caller may not see.
PUBLIC_BY_DESIGN: dict[str, str] = {
    "/": "service banner: name, version, endpoint index",
    "/health": "liveness probe consumed by installers and monitors",
    "/v2/health": "versioned liveness probe, same content shape",
    "/metrics": "Prometheus scrape target (counters, no payloads)",
    "/v1/metrics": "JSON twin of /metrics for the dashboard",
    "/openapi.json": "API schema, mirrors the published documentation",
    "/api-docs": "same schema under the documentation alias",
    "/gui": "dashboard shell; the app authenticates client-side",
    "/gui/v2": "dashboard login page — must render before any token exists",
    "/sse": "event stream; emits nothing until a token is presented",
    "/v1/version": (
        "version + interpreter + platform string; the same facts /health "
        "already publishes, and installers read it before holding a token"
    ),
    "/gui/assets/manifest.json": (
        "list of dashboard script URLs; the login page must fetch it before "
        "any token exists, and it exposes no state"
    ),
}

# Endpoints that legitimately answer 2xx to a credential-less request because
# they are protocol handshakes returning an error *envelope* rather than data.
PROTOCOL_ENVELOPE: dict[str, str] = {
    "/mcp": "JSON-RPC: unauthenticated calls get a JSON-RPC error object",
    "/messages": "MCP SSE message sink, same envelope contract",
}

# 429 belongs here too: require_auth() answers 429 instead of 401 once an IP
# accumulates 10 failed attempts in 60s (arena/auth/runtime.py). That is the
# brute-force throttle refusing the caller — still a refusal, still no data.
# A sweep like this one trips it by design after the first ten routes.
REFUSAL_STATUSES = {401, 403, 429}
# 404/405 mean the route rejected the probe before auth could matter;
# 400 means the payload was rejected first. Neither exposes data.
BENIGN_STATUSES = {400, 404, 405, 422}


class _QuietAuthWarnings:
    """Mute the auth throttle logger for the sweep.

    Deliberately failing auth ~200 times makes require_auth emit one WARNING
    per probe, burying real output under hundreds of identical lines.
    """

    def __enter__(self):
        import logging

        self._log = logging.getLogger("arena-bridge")
        self._prev = self._log.level
        self._log.setLevel(logging.ERROR)
        return self

    def __exit__(self, *exc):
        self._log.setLevel(self._prev)
        return False


class _LimiterOff:
    """Silence the traffic rate limiters while sweeping.

    Both limiters run BEFORE authentication, so a 200-route sweep would
    otherwise measure throughput instead of auth. (The separate brute-force
    throttle inside require_auth still fires, and that is fine — its 429 is
    counted as a refusal.)
    """

    def __enter__(self):
        from arena import rate_limit as rl

        self._rl = rl
        self._v1_max = rl._rate_limit_max
        self._v2_enabled = rl._rl_v2_config["enabled"]
        rl._rate_limit_max = 10 ** 9
        rl._rl_v2_config["enabled"] = False
        rl._rate_limit_store.clear()
        rl._rl_v2_store.clear()
        return self

    def __exit__(self, *exc):
        self._rl._rate_limit_max = self._v1_max
        self._rl._rl_v2_config["enabled"] = self._v2_enabled
        # Clearing the store on the way OUT matters more than on the way in:
        # this sweep deliberately fails auth ~200 times, and require_auth
        # records those under "auth_fail:<peer>" in this very dict. Leaving
        # them behind arms the brute-force throttle for every later test in
        # the session — which is exactly how this guard first broke three
        # unrelated mission/extension tests.
        self._rl._rate_limit_store.clear()
        self._rl._rl_v2_store.clear()
        return False


def _build_app() -> web.Application:
    """Build the real app, then detach its lifecycle hooks.

    ``on_cleanup`` tears down process-wide resources — most importantly the
    shared _SLOW_EXECUTOR. Letting it run at the end of this test poisons
    every later test in the session with "cannot schedule new futures after
    shutdown" (it broke three mission/extension tests before this line
    existed). Routing and auth do not need the background workers, so the
    guard builds the router and skips the lifecycle entirely.
    """
    app = _make_raw_app()
    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_shutdown.clear()
    return app


def _make_raw_app() -> web.Application:
    return ub.make_app(
        {
            "token": "guard-token-not-used-by-probe",
            "profile": "owner-shell",
            "root": Path("/tmp"),
            "active_exec": 0,
            "max_concurrent": 3,
            "audit": "audit",
            "timeout": 60,
            "max_timeout": 3600,
            "max_output": 2000000,
            "allow_any_cwd": False,
            "semaphore": asyncio.Semaphore(1),
        }
    )


def _iter_probeable_routes(app: web.Application):
    """Yield (method, path) pairs worth probing.

    HEAD is skipped: aiohttp mirrors it from GET, so it adds no coverage.
    Templated paths get placeholder values — the point is reaching the
    handler, not exercising its arguments.
    """
    seen: set[tuple[str, str]] = set()
    for route in app.router.routes():
        method = route.method
        if method == "HEAD":
            continue
        info = route.resource.get_info()
        path = info.get("path") or info.get("formatter")
        if not path:
            continue
        # v4.164.0: template variables are FILLED IN, not truncated.
        #
        # This used to keep `{path}` and then cut everything from the
        # first remaining `{`, so `/v1/bore/tunnel/{action}` was probed
        # as `/v1/bore/tunnel` -- a path no route serves. That answered
        # 404, 404 is in BENIGN_STATUSES, and the route was recorded as
        # checked while never being reached. 66 of 274 registered routes
        # (every one with a parameter other than `{path}`) were invisible
        # to this guard, and `POST /v1/bore/tunnel/status` really was
        # unauthenticated behind that blind spot -- bug #57.
        #
        # Substituting a plausible value reaches the handler, which is
        # the entire point of the sweep. `{action}` gets "status"
        # specifically: the tunnel handlers dispatch on it, and a value
        # they reject would return 400 and be waved through as benign
        # for the same reason.
        concrete = path
        for variable, value in (
            ("{path:.*}", "probe"),
            ("{path}", "probe"),
            ("{action}", "status"),
            ("{transport}", "ngrok"),
            ("{serial}", "probe-serial"),
            ("{run_id}", "probe-run"),
            ("{rec_id}", "probe-rec"),
            ("{nwid}", "0" * 16),
            ("{name}", "probe"),
            ("{id}", "probe"),
        ):
            concrete = concrete.replace(variable, value)
        # Anything still templated gets a generic filler rather than
        # being cut short.
        concrete = re.sub(r"\{[^}]+\}", "probe", concrete)
        key = (method, concrete)
        if key in seen:
            continue
        seen.add(key)
        yield method, concrete, path


async def _probe(client: TestClient, method: str, path: str):
    kwargs = {}
    if method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = {}
    return await client.request(method, path, **kwargs)


def test_every_route_refuses_anonymous_callers():
    """No route may serve an unauthenticated caller unless allow-listed."""

    async def _run():
        app = _build_app()
        async with TestClient(TestServer(app)) as client:
            unguarded: list[str] = []
            checked = 0
            for method, concrete, declared in _iter_probeable_routes(app):
                base = concrete.split("?")[0].rstrip("/") or "/"
                if base in PUBLIC_BY_DESIGN or base in PROTOCOL_ENVELOPE:
                    continue
                try:
                    resp = await _probe(client, method, concrete)
                except Exception:
                    # A transport-level failure is not an auth bypass.
                    continue
                checked += 1
                if resp.status in REFUSAL_STATUSES or resp.status in BENIGN_STATUSES:
                    continue
                if resp.status >= 500:
                    # Crashing is a different bug class; this guard is about
                    # exposure, and a 500 body is not attacker-useful data.
                    continue
                unguarded.append(f"{resp.status} {method} {declared}")
            return checked, unguarded

    with _LimiterOff(), _QuietAuthWarnings():
        checked, unguarded = asyncio.run(_run())
    assert checked > 100, (
        f"only {checked} routes probed — the walker stopped seeing the "
        "router; fix the guard before trusting it"
    )
    assert not unguarded, (
        "Routes answered an unauthenticated caller and are not "
        "allow-listed:\n  " + "\n  ".join(sorted(unguarded)) +
        "\n\nEither call require_auth() in the handler, or add the path "
        "to PUBLIC_BY_DESIGN with the reason it is safe."
    )


def test_allowlist_describes_routes_that_actually_exist():
    """The allow-list must describe reality, not aspirations.

    A stale exemption is worse than none: it silently widens the guard for a
    path nobody serves any more, and hides the day someone re-adds it.
    """
    app = _build_app()
    registered = {
        (concrete.split("?")[0].rstrip("/") or "/")
        for _m, concrete, _d in _iter_probeable_routes(app)
    }
    stale = [p for p in PUBLIC_BY_DESIGN if p not in registered]
    assert not stale, (
        f"PUBLIC_BY_DESIGN lists paths the app no longer serves: {sorted(stale)}"
    )


def test_allowlist_entries_carry_a_justification():
    """Every exemption must say why it is safe — silence is not a reason."""
    for path, reason in {**PUBLIC_BY_DESIGN, **PROTOCOL_ENVELOPE}.items():
        assert reason.strip(), f"{path} is exempted without a justification"
        assert len(reason) > 15, f"{path}: justification too thin: {reason!r}"


def test_the_sweep_actually_reaches_templated_routes():
    """Guard the guard: a truncated probe path proves nothing.

    Until v4.164.0 this sweep cut every path at its first `{`, so
    `/v1/bore/tunnel/{action}` was requested as `/v1/bore/tunnel`. No
    route serves that, the 404 counted as benign, and 66 of 274
    registered routes were recorded as "checked" without their handlers
    ever running. One of them was genuinely unauthenticated.

    A route counted as checked must therefore be a route that answered
    something other than "no such path".

    Static-file routes are the honest exception: `/gui/assets/{path}`
    reaches its handler and *then* returns 404 because no file called
    "probe" exists. That 404 comes from the handler, not from the
    router, so those two are named explicitly rather than allowed by a
    pattern -- a rule like "skip anything under /gui" would grow to hide
    real gaps.
    """
    handler_serves_404 = {"/gui/assets/{path}", "/gui/docs/{path}"}

    async def _run():
        app = _build_app()
        async with TestClient(TestServer(app)) as client:
            missing = []
            probed = 0
            for method, concrete, declared in _iter_probeable_routes(app):
                if "{" not in declared or declared in handler_serves_404:
                    continue
                base = concrete.split("?")[0].rstrip("/") or "/"
                if base in PUBLIC_BY_DESIGN or base in PROTOCOL_ENVELOPE:
                    continue
                probed += 1
                try:
                    resp = await _probe(client, method, concrete)
                except Exception:
                    continue
                if resp.status == 404:
                    missing.append(f"{method} {declared} -> probed {concrete}")
            return probed, missing

    with _LimiterOff(), _QuietAuthWarnings():
        probed, missing = asyncio.run(_run())

    assert probed >= 40, (
        f"only {probed} templated routes seen; the walker or the registry "
        "changed shape and this guard is no longer measuring anything"
    )
    assert not missing, (
        "these templated routes were probed at a path that does not exist, "
        "so their handlers never ran and their auth was never tested:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nAdd the template variable to the substitution table in "
          "_iter_probeable_routes."
    )
