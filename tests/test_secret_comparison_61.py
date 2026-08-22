"""Secret comparison must be constant-time *and* total (#61).

Issue #61 reported a docstring lie: `AgentRegistry.resolve_token`
claimed constant-time comparison "via `hmac.compare_digest` inside
`_derive_agent_token`" while resolving the token with a plain dict
lookup. `_derive_agent_token` mints a token with `hmac.new`; it
compares nothing.

Fixing that the way the issue suggests -- dropping `hmac.compare_digest`
straight into the loop -- introduces a worse bug than the one it fixes.
`hmac.compare_digest` accepts `str` only while *both* operands are pure
ASCII, and every credential here arrives from the network. That hazard
was not hypothetical: measured against the live bridge before this
change,

    GET /v1/status  Authorization: Bearer <u-umlaut>         -> 500
    GET /v1/status  Authorization: Bearer agent-<uml>-attack -> 500
    GET /gui?token=%C3%BC                                    -> 500
    GET /v1/status  Authorization: Bearer agent-deadbeef-... -> 401

Unauthenticated requests turning into unhandled TypeErrors, on paths
whose entire job is to answer 401. So this module asserts both
properties: the comparison sits on the constant-time path, and no input
can make an auth check raise.
"""
from __future__ import annotations

import asyncio
import hmac
import inspect
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

import unified_bridge as ub
from arena.auth.compare import secrets_equal
from arena.multiagent import agents as A

MASTER = "master-secret-61"

#: Credentials an attacker can send that `hmac.compare_digest` refuses
#: to compare as `str`. Each one used to be an HTTP 500.
HOSTILE = [
    pytest.param("agent-\u00fc-attack", id="latin1-umlaut"),
    pytest.param("\u00fc", id="bare-umlaut"),
    pytest.param("\u0440\u0443\u0441", id="cyrillic"),
    pytest.param("\U0001F600", id="emoji"),
    pytest.param("agent-deadbeef-\u00ff\u00ff", id="agent-prefixed-non-ascii"),
]


# --- the comparator itself -------------------------------------------------


@pytest.mark.parametrize("hostile", HOSTILE)
def test_raw_compare_digest_is_the_hazard_being_fixed(hostile):
    """Anchor the premise: the stdlib call really does raise on this input.

    If a future Python makes `hmac.compare_digest` total over `str`,
    this test fails and the whole module can be reconsidered. Without
    it, the assertions below would look like superstition.
    """
    with pytest.raises(TypeError):
        hmac.compare_digest(hostile, "agent-deadbeef-0123456789abcdef")


@pytest.mark.parametrize("hostile", HOSTILE)
def test_secrets_equal_answers_instead_of_raising(hostile):
    assert secrets_equal(hostile, "agent-deadbeef-0123456789abcdef") is False
    assert secrets_equal("agent-deadbeef-0123456789abcdef", hostile) is False


def test_secrets_equal_handles_lone_surrogates():
    """A latin-1-decoded header can carry unpaired surrogates.

    Plain `.encode("utf-8")` raises UnicodeEncodeError on those, which
    would reintroduce the crash through the back door.
    """
    assert secrets_equal("\udcff", "abc") is False
    assert secrets_equal("\udcff", "\udcff") is True


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("abc", "abc", True),
        ("abc", "abd", False),
        ("", "", True),
        ("", "abc", False),
        ("abc", "abcd", False),
        ("\u00fc", "\u00fc", True),           # equal non-ASCII still matches
        ("\U0001F600", "\U0001F600", True),
        (b"abc", "abc", True),                # bytes/str mix
        ("abc", b"abc", True),
        (b"abc", b"abc", True),
    ],
)
def test_secrets_equal_agrees_with_equality(left, right, expected):
    assert secrets_equal(left, right) is expected


@pytest.mark.parametrize("junk", [None, 123, 4.5, {"a": 1}, ["a"], object()])
def test_non_string_secrets_compare_false_not_crash(junk):
    """A JSON body can decode to anything; a non-string is not a secret."""
    assert secrets_equal(junk, "abc") is False
    assert secrets_equal("abc", junk) is False


def test_secrets_equal_uses_the_constant_time_primitive(monkeypatch):
    """The point of the helper is `compare_digest`, not `==`."""
    calls = []
    real = hmac.compare_digest

    def _spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", _spy)
    assert secrets_equal("abc", "abc") is True
    assert calls, "secrets_equal bypassed hmac.compare_digest"
    assert all(
        isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls
    ), "operands must reach compare_digest as bytes, which is total"


# --- #61 proper: the registry lookup ---------------------------------------


@pytest.fixture
def registry():
    reg = A.AgentRegistry()
    yield reg
    reg.reset()


def test_resolve_token_is_on_the_constant_time_path(registry, monkeypatch):
    """The headline of #61: comparison must not be a dict lookup."""
    rec = registry.create(label="a", master_token=MASTER)
    seen = []
    monkeypatch.setattr(
        "arena.multiagent.agents.secrets_equal",
        lambda a, b: (seen.append((a, b)), a == b)[1],
    )

    assert registry.resolve_token(rec.token) is rec
    assert seen, "resolve_token still resolves without a timing-safe compare"

    seen.clear()
    assert registry.resolve_token("agent-deadbeef-0000000000000000") is None
    assert seen, "a miss must also go through the timing-safe compare"


def test_resolve_token_scan_length_does_not_depend_on_the_guess(
        registry, monkeypatch):
    """A `break` on first hit would leak the match position by timing."""
    tokens = [registry.create(label=f"a{i}", master_token=MASTER).token
              for i in range(5)]
    counts = []
    real = A.secrets_equal
    monkeypatch.setattr(
        "arena.multiagent.agents.secrets_equal",
        lambda a, b: (counts.append(1), real(a, b))[1],
    )

    for token in (tokens[0], tokens[-1], "agent-deadbeef-0000000000000000"):
        counts.clear()
        registry.resolve_token(token)
        assert len(counts) == len(tokens), (
            f"scanned {len(counts)} of {len(tokens)} tokens: the number of "
            "comparisons leaks where the match sits"
        )


def test_resolve_token_docstring_no_longer_makes_the_false_claim():
    """#61 was filed against the docstring; the lie must not survive."""
    doc = inspect.getdoc(A.AgentRegistry.resolve_token) or ""
    assert doc, "resolve_token lost its docstring"
    claim = "`hmac.compare_digest` inside `_derive_agent_token`"
    # The fixed docstring quotes the old claim to explain what changed,
    # so only the text before that explanation is checked.
    body = doc.split("Before #61")[0]
    assert claim not in body, (
        "the docstring still asserts constant-time comparison happens "
        "inside _derive_agent_token, which only mints tokens"
    )


@pytest.mark.parametrize("hostile", HOSTILE)
def test_resolve_token_survives_hostile_tokens(registry, hostile):
    """The naive #61 fix crashes here; this one must not."""
    registry.create(label="victim", master_token=MASTER)
    assert registry.resolve_token(hostile) is None


def test_resolve_token_still_resolves_and_revokes(registry):
    """Constant-time must not mean broken."""
    a = registry.create(label="a", master_token=MASTER)
    b = registry.create(label="b", master_token=MASTER)

    assert registry.resolve_token(a.token) is a
    assert registry.resolve_token(b.token) is b
    assert registry.resolve_token("") is None
    assert registry.resolve_token(a.token + "x") is None

    assert registry.revoke(a.agent_id) is True
    assert registry.resolve_token(a.token) is None, "revocation stopped working"
    assert registry.resolve_token(b.token) is b


# --- the roster path, which only runs when users are configured ------------


@pytest.mark.parametrize("hostile", HOSTILE)
def test_hostile_token_against_a_configured_roster(tmp_path, hostile):
    """`check_auth_with_role` scans the roster before the cfg token.

    That branch is skipped entirely when no users are configured, so a
    test using the default empty roster never reaches its comparison
    and cannot see a regression there. A roster is written here on
    purpose.
    """
    from aiohttp.test_utils import make_mocked_request

    from arena.app_keys import APP_CFG
    from arena.auth.users import UserStore

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": [
        {"token": "roster-token-61", "role": "user", "name": "u61"},
    ]}), encoding="utf-8")
    store = UserStore(users_file=users_file)
    assert store.load_users(), "roster fixture did not load; test is vacuous"

    app = {APP_CFG: {"token": MASTER}}
    request = make_mocked_request(
        "GET", "/v1/status",
        headers={"Authorization": f"Bearer {hostile}"}, app=app)

    # Must answer, not raise: this is the crash path.
    ok, role = store.check_auth_with_role(request)
    assert ok is False and role == ""


def test_configured_roster_still_authenticates_its_users(tmp_path):
    """Guard the fix against a comparator that just returns False."""
    from aiohttp.test_utils import make_mocked_request

    from arena.app_keys import APP_CFG
    from arena.auth.users import UserStore

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": [
        {"token": "roster-token-61", "role": "user", "name": "u61"},
    ]}), encoding="utf-8")
    store = UserStore(users_file=users_file)
    app = {APP_CFG: {"token": MASTER}}

    def _ask(bearer):
        return store.check_auth_with_role(make_mocked_request(
            "GET", "/v1/status",
            headers={"Authorization": f"Bearer {bearer}"}, app=app))

    assert _ask("roster-token-61") == (True, "user")
    assert _ask(MASTER) == (True, "admin"), "cfg token fallback broke"
    assert _ask("roster-token-62") == (False, "")


# --- the input helper, a standalone script with its own copy ---------------


def _load_helper_server():
    """Import `helper_server.py` the way it actually runs: as a script.

    It is started with `python helper_server.py`, outside the package,
    so it must not depend on `arena` being importable. That is why it
    carries its own copy of the comparator instead of importing
    `arena.auth.compare` -- and why the copy needs its own test.
    """
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "arena" / "input_helper" \
        / "helper_server.py"
    spec = importlib.util.spec_from_file_location("_helper_server_61", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("hostile", HOSTILE)
def test_input_helper_auth_survives_hostile_header(hostile):
    """This token guards keystroke injection into the live desktop."""
    helper = _load_helper_server()
    assert helper._secrets_equal(f"Bearer {hostile}", "Bearer real") is False


def test_input_helper_auth_still_accepts_the_real_token():
    helper = _load_helper_server()
    assert helper._secrets_equal("Bearer real", "Bearer real") is True
    assert helper._secrets_equal("Bearer wrong", "Bearer real") is False


def test_input_helper_auth_check_survives_hostile_header():
    """The call site, not just the helper: `_check_auth` must not raise.

    Exercising only `_secrets_equal` would keep passing if the handler
    went back to calling `hmac.compare_digest` directly.
    """
    helper = _load_helper_server()

    class _FakeHandler(helper.InputHandler):
        def __init__(self, header):  # noqa: D107 -- no socket setup
            self.headers = {"Authorization": header}
            self.sent = []

        def send_response(self, code):
            self.sent.append(code)

        def end_headers(self):
            pass

        @property
        def wfile(self):
            class _Sink:
                def write(self, _data):
                    pass
            return _Sink()

    helper._TOKEN = "real-token-61"
    for hostile in ("\u00fc", "\u0440\u0443\u0441", "\U0001F600"):
        handler = _FakeHandler(f"Bearer {hostile}")
        assert handler._check_auth() is False
        assert handler.sent == [401], "hostile header must yield 401"

    handler = _FakeHandler("Bearer real-token-61")
    assert handler._check_auth() is True, "the real token stopped working"


def test_input_helper_copy_matches_the_package_comparator():
    """The duplicate is deliberate; drift between the two is not."""
    helper = _load_helper_server()
    cases = ["", "abc", "\u00fc", "\u0440\u0443\u0441", "\U0001F600",
             "Bearer real", "\udcff"]
    for left in cases:
        for right in cases:
            assert helper._secrets_equal(left, right) is \
                secrets_equal(left, right), (
                f"standalone copy disagrees on {left!r} vs {right!r}"
            )


# --- the public-tunnel acknowledgement, read from a JSON request body ------


def _same_length_hostile_acks():
    """Non-ASCII acks that reach the comparison.

    The call site guards on `len(ack) == len(PUBLIC_TUNNEL_ACK)` first,
    so the short strings in HOSTILE are rejected by length and never
    reach `compare_digest`. Only a same-length non-ASCII ack exercises
    the crash path -- a detail worth stating, since testing with the
    short ones looks equivalent and silently proves nothing.
    """
    from arena.admin.tunnel_exposure_policy import PUBLIC_TUNNEL_ACK

    n = len(PUBLIC_TUNNEL_ACK)
    return [
        pytest.param("\u00fc" * n, id="umlaut-run"),
        pytest.param(PUBLIC_TUNNEL_ACK[:-1] + "\u00fc", id="last-char-umlaut"),
        pytest.param("\U0001F600" * n, id="emoji-run"),
        pytest.param("\u0440" * n, id="cyrillic-run"),
    ]


@pytest.mark.parametrize("hostile", _same_length_hostile_acks())
def test_public_tunnel_ack_survives_hostile_input(hostile):
    """`ack` comes straight out of a JSON body the caller controls.

    Exposing the bridge to the public internet is gated on an exact
    acknowledgement string. A non-ASCII `ack` must be a denial, not a
    TypeError out of the admin handler.
    """
    from arena.admin.tunnel_exposure_policy import (
        PUBLIC_TUNNEL_ACK,
        public_start_denial,
    )

    assert len(hostile) == len(PUBLIC_TUNNEL_ACK), (
        "fixture must clear the length guard, else the test is vacuous"
    )
    denial = public_start_denial(
        provider="cloudflared", action="start", ack=hostile)
    assert denial is not None, "a wrong ack must be denied"
    assert denial["error"] == "tunnel_public_ack_required"


@pytest.mark.parametrize("junk", [None, 123, {"a": 1}, ["a"]])
def test_public_tunnel_ack_ignores_non_string_bodies(junk):
    """`ack` is whatever JSON decoded to; it need not be a string."""
    from arena.admin.tunnel_exposure_policy import public_start_denial

    denial = public_start_denial(
        provider="cloudflared", action="start", ack=junk)
    assert denial is not None and denial["error"] == "tunnel_public_ack_required"


def test_public_tunnel_ack_still_accepts_the_exact_string():
    """Denying everything would also satisfy the test above."""
    from arena.admin.tunnel_exposure_policy import (
        PUBLIC_TUNNEL_ACK,
        public_start_denial,
    )

    assert public_start_denial(
        provider="cloudflared", action="start",
        ack=PUBLIC_TUNNEL_ACK) is None, "the exact ack stopped being accepted"


# --- the signed URL cache, whose file an attacker may control --------------


def test_tampered_cache_signature_is_refused_not_a_crash(tmp_path,
                                                          monkeypatch):
    """`url_cache.load` verifies a signature from a file on disk.

    Not a network input, but the module's own docstring calls the file
    an attacker target: whoever can write the user's home picks `sig`.
    A non-ASCII `sig` would raise TypeError out of a CLI bootstrap
    instead of refusing to trust the cache.
    """
    from arena.agentctl_cli import url_cache

    path = tmp_path / "last_urls.json"
    monkeypatch.setattr(url_cache, "cache_path", lambda: path)
    monkeypatch.delenv("ARENA_URL_CACHE_DISABLE", raising=False)

    for hostile_sig in ("\u00fc", "\u0440\u0443\u0441", "\U0001F600"):
        path.write_text(json.dumps({
            "envelope_version": url_cache.ENVELOPE_VERSION,
            "sig": hostile_sig,
            "payload": {"version": url_cache.CACHE_VERSION,
                        "urls": ["https://evil.example"]},
        }), encoding="utf-8")
        assert url_cache.load("secret-61") is None, (
            f"a cache signed {hostile_sig!r} must be refused, not trusted"
        )


def test_correctly_signed_cache_is_still_accepted(tmp_path, monkeypatch):
    """Refusing everything would also pass the test above."""
    from arena.agentctl_cli import url_cache

    path = tmp_path / "last_urls.json"
    monkeypatch.setattr(url_cache, "cache_path", lambda: path)
    monkeypatch.delenv("ARENA_URL_CACHE_DISABLE", raising=False)

    payload = {
        "version": url_cache.CACHE_VERSION,
        "urls": ["https://pc.example.ts.net"],
        "saved_at": 0,
    }
    path.write_text(json.dumps({
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": url_cache._sign(payload, "secret-61"),
        "payload": payload,
    }), encoding="utf-8")

    loaded = url_cache.load("secret-61")
    assert loaded is not None, "a correctly signed cache stopped loading"


# --- the live surface: no credential may produce a 500 ---------------------


async def _get(path, headers=None, params=None):
    cfg = {
        "token": MASTER, "bind": "127.0.0.1", "root": "/tmp",
        "max_concurrent": 4, "profile": "default",
    }
    app = ub.make_app(cfg)
    # `make_app` registers an on_cleanup hook that shuts down the
    # process-wide ub._EXECUTOR. Letting it run would break every later
    # test in the session, so the app is torn down without it.
    app.on_cleanup.clear()
    server = TestServer(app)
    await server.start_server()
    client = TestClient(server)
    try:
        resp = await client.get(path, headers=headers or {},
                                params=params or {})
        return resp.status, await resp.text()
    finally:
        await client.close()
        await server.close()


def _serve(path, **kw):
    return asyncio.run(_get(path, **kw))


@pytest.mark.parametrize("hostile", HOSTILE)
def test_hostile_bearer_token_is_rejected_not_a_server_error(hostile):
    """Measured as HTTP 500 on the live bridge before this fix."""
    status, _ = _serve("/v1/status",
                       headers={"Authorization": f"Bearer {hostile}"})
    assert status != 500, (
        f"Bearer {hostile!r} crashed the auth path; an unauthenticated "
        "caller must never be able to force a 500"
    )
    assert status == 401, "a bogus credential must be refused, not accepted"


@pytest.mark.parametrize("hostile", HOSTILE)
def test_hostile_gui_query_token_is_rejected_not_a_server_error(hostile):
    """`/gui?token=<non-ascii>` returned 500 on the live bridge too.

    The GUI answers 200 either way -- login page or dashboard -- so the
    body decides. Asserting only on the status would pass even if the
    dashboard were handed to an anonymous caller.
    """
    status, body = _serve("/gui", params={"token": hostile})
    assert status != 500, f"?token={hostile!r} crashed the GUI login route"
    assert "login" in body.lower(), (
        "a bogus GUI token must land on the login page, not the dashboard"
    )


def test_the_real_credentials_still_authenticate():
    """The gate must still open for the operator.

    `/v1/status` is deliberately not used for the positive case: with
    the minimal cfg above it answers 500 with `{"error": "\'active_exec\'"}`
    on unmodified master too, long before this change -- a missing cfg
    key, not an auth verdict. Asserting 200 there would be asserting an
    unrelated bug. The GUI route reaches the comparator with no such
    dependency, and distinguishes accept from reject by body.
    """
    status, body = _serve("/gui", params={"token": MASTER})
    assert status == 200
    assert "login" not in body.lower(), (
        "a valid GUI token must reach the dashboard, not the login page"
    )


def test_the_master_token_is_still_accepted_by_the_auth_check():
    """The API-side verdict, asserted on the check rather than a route.

    Complements the GUI test above without depending on a route whose
    cfg requirements are unrelated to authentication.
    """
    from arena.auth import runtime as auth_runtime

    async def _check(bearer):
        cfg = {"token": MASTER, "bind": "127.0.0.1", "root": "/tmp",
               "max_concurrent": 4, "profile": "default"}
        app = ub.make_app(cfg)
        app.on_cleanup.clear()
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        try:
            # /v1/version is public but still runs the auth probe.
            resp = await client.get(
                "/v1/version", headers={"Authorization": f"Bearer {bearer}"})
            return json.loads(await resp.text())
        finally:
            await client.close()
            await server.close()

    assert auth_runtime is not None
    body = asyncio.run(_check(MASTER))
    assert "python" in body, (
        "the master token no longer authenticates: /v1/version withheld "
        "the fields it gates behind auth (#63)"
    )

    body = asyncio.run(_check("agent-deadbeef-0123456789abcdef"))
    assert "python" not in body, "a bogus token was treated as authenticated"
