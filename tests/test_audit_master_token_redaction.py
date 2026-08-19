"""The bridge's own bearer must never reach the audit log (#132).

Reproduced on the live install (v4.169.48) before the fix: `POST /v1/exec`
with the token on the command line wrote it verbatim into `audit.jsonl`,
where `audit.export` hands it to any authenticated caller. Two independent
defects made that possible and both are covered here:

1. no credential-shape pattern can match the token -- it is 43 characters of
   unstructured base62, with no prefix, separator or checksum;
2. the header and assignment spellings that *are* shaped (`X-Arena-Token:`,
   `BRIDGE_TOKEN=`, `?token=`) had no patterns either.

The literal registry closes (1); new patterns close (2). Both are tested,
because either alone leaves a live leak: patterns miss a bare token, and the
registry misses a token this process does not know (a peer bridge's).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# See tests/test_cdp_navigation_policy.py: no conftest puts the repository
# root on sys.path, so the imports below are E402 by design.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.cli import build_parser  # noqa: E402
from arena.observability.audit import sanitize_audit_event  # noqa: E402
from arena.observability.redact import (  # noqa: E402
    LITERAL_MIN_LENGTH,
    redact_string,
    register_literal_secret,
    registered_literal_count,
    unregister_literal_secret,
)

# Synthetic, same shape as a real bridge token (unstructured base62).
# Never use the live value in a test: it would put the credential in git.
#
# Assembled from fragments at import time, never written as one literal:
# a complete credential-shaped string is what secret scanners match on,
# and gitleaks duly failed this PR on the inlined form (generic-api-key,
# entropy 5.29). Same rule as tests/test_observability_redact.py.
FAKE_TOKEN = "K3xq" + "PzTvNbWm7YdRc2Hs" + "LgEu9AjFtQ5ZnVpXyB4"


def _isolate_registry(monkeypatch, redact_mod):
    """Give a test an empty registry without leaking into its neighbours.

    Both the dict and the published snapshot must be reset: readers use
    the snapshot, so clearing only the dict would leave a stale literal
    live (the test would pass for the wrong reason) -- and clearing only
    the snapshot would let the next registration resurrect the old one.
    """
    monkeypatch.setattr(redact_mod, "_LITERAL_SECRETS", {}, raising=True)
    monkeypatch.setattr(redact_mod, "_LITERAL_SNAPSHOT", (), raising=True)


@pytest.fixture
def registered():
    """Register the fake token and always clean up.

    The registry is module-level state, so a leaked registration would make
    unrelated tests pass for the wrong reason.
    """
    register_literal_secret(FAKE_TOKEN, kind="bridge-token")
    try:
        yield FAKE_TOKEN
    finally:
        unregister_literal_secret(FAKE_TOKEN)


# --- the literal registry ----------------------------------------------------

@pytest.mark.parametrize("event", [
    {"cmd": f"echo {FAKE_TOKEN}"},
    {"cmd": f"curl -H 'X-Arena-Token: {FAKE_TOKEN}' http://127.0.0.1:8765/"},
    {"cmd": f"BRIDGE_TOKEN={FAKE_TOKEN} ./run.sh"},
    {"cmd": f"curl 'http://127.0.0.1:8765/v1/status?token={FAKE_TOKEN}'"},
    {"args": ["echo", FAKE_TOKEN]},
    {"meta": {"nested": [{"deep": f"prefix{FAKE_TOKEN}suffix"}]}},
    {"note": f"the token is {FAKE_TOKEN}, do not share"},
])
def test_the_master_token_never_survives_sanitisation(event, registered):
    assert FAKE_TOKEN not in repr(sanitize_audit_event(dict(event)))


def test_the_redaction_marker_names_the_secret_kind(registered):
    out = sanitize_audit_event({"cmd": f"echo {FAKE_TOKEN}"})
    assert out["cmd"] == "echo <redacted:bridge-token>"


def test_a_bare_token_leaks_without_registration():
    """Positive control: the shape patterns genuinely cannot catch it.

    If this ever starts passing, a new pattern is matching unstructured
    base62 -- which would also redact commit SHAs and file hashes across the
    whole audit log, and the registry's rationale would need rewriting.
    """
    assert FAKE_TOKEN in sanitize_audit_event({"cmd": f"echo {FAKE_TOKEN}"})["cmd"]


def test_the_short_string_fast_path_does_not_skip_a_registered_literal():
    """A literal shorter than the 16-char pattern fast path still redacts."""
    short = "x" * LITERAL_MIN_LENGTH
    register_literal_secret(short, kind="test-secret")
    try:
        assert redact_string(short) == "<redacted:test-secret>"
    finally:
        unregister_literal_secret(short)


@pytest.mark.parametrize("value", ["", "   ", "abc", "short", None, 12345, b"bytes"])
def test_useless_literals_are_refused(value):
    """Registering "" would redact every string; registering "1" is worse.

    The call reports refusal rather than accepting silently, so a caller
    passing a missing config key cannot believe it is protected.
    """
    before = registered_literal_count()
    assert register_literal_secret(value) is False
    assert registered_literal_count() == before


def test_registration_is_idempotent():
    before = registered_literal_count()
    assert register_literal_secret(FAKE_TOKEN) is True
    assert register_literal_secret(FAKE_TOKEN) is True
    try:
        assert registered_literal_count() == before + 1
    finally:
        unregister_literal_secret(FAKE_TOKEN)


def test_unregistering_stops_the_substitution():
    register_literal_secret(FAKE_TOKEN)
    unregister_literal_secret(FAKE_TOKEN)
    assert FAKE_TOKEN in redact_string(f"echo {FAKE_TOKEN}")


def test_the_count_helper_does_not_expose_the_values():
    """A diagnostic that dumped the registry would recreate the leak."""
    register_literal_secret(FAKE_TOKEN)
    try:
        assert isinstance(registered_literal_count(), int)
        assert FAKE_TOKEN not in repr(registered_literal_count())
    finally:
        unregister_literal_secret(FAKE_TOKEN)


# --- the shape patterns (work without registration) --------------------------

@pytest.mark.parametrize("text,marker", [
    (f"curl -H 'X-Arena-Token: {FAKE_TOKEN}' http://x/", "arena-token-header"),
    (f"curl -H 'x-arena-token:{FAKE_TOKEN}' http://x/", "arena-token-header"),
    (f"BRIDGE_TOKEN={FAKE_TOKEN} ./run.sh", "token-assignment"),
    (f"ARENA_BRIDGE_TOKEN='{FAKE_TOKEN}' ./run.sh", "token-assignment"),
    (f"export API_KEY={FAKE_TOKEN}", "token-assignment"),
    (f"curl 'http://x/v1/status?token={FAKE_TOKEN}'", "query-credential"),
    (f"curl 'http://x/?a=1&access_token={FAKE_TOKEN}'", "query-credential"),
])
def test_unknown_tokens_are_caught_by_shape_alone(text, marker):
    """These must work for a token this process never learned."""
    out = redact_string(text)
    assert FAKE_TOKEN not in out
    assert f"<redacted:{marker}>" in out


@pytest.mark.parametrize("benign", [
    "commit 4b777d8e1f3a9c2b5d6e7f8a9b0c1d2e3f4a5b6c is the parent",
    "sha256=ba4966b4da9bd643e13a319dc316066ffb9fd734dcf41968692c783c486f8946",
    "GET /v1/status?verbose=true&format=json",
    "python3 -m pytest tests/test_observability_redact.py -q",
    "TOKEN_FILE=/home/user/arena-bridge/token.txt",
])
def test_ordinary_audit_lines_are_left_alone(benign):
    """Over-redaction destroys the audit's usefulness as a review surface.

    A hash or a commit SHA is long unstructured hex; a pattern broad enough
    to catch a bare token by shape would eat all of these.
    """
    assert redact_string(benign) == benign


# --- wiring: the registry must actually be populated -------------------------
#
# Everything above tests the mechanism. These test that the mechanism is
# switched on: a perfect redactor that nobody registers the token with leaves
# the leak exactly as it was.

def test_serve_registers_the_bridge_token_with_the_redactor(monkeypatch, tmp_path):
    """Drive the real `serve()` and assert the token is scrubbed afterwards."""
    from aiohttp import web

    from arena.cli import CliContext, serve
    from arena.observability import redact as redact_mod

    startup_token = "S3rv3Startup" + "TokenAbcdefghijklmnop"

    _isolate_registry(monkeypatch, redact_mod)
    assert startup_token in redact_string(f"echo {startup_token}")

    ctx = CliContext(
        version="test-version",
        audit_path=tmp_path / "audit.jsonl",
        default_max_output=123,
        default_max_concurrent=4,
        cdp_state={},
        make_app=lambda cfg: web.Application(),
        resolve_token=lambda token: (startup_token, tmp_path / "token.txt"),
        token_generator=lambda: "generated-token",
        daemonize=lambda: None,
        ensure_session_env=lambda: None,
        load_config_file=lambda: {},
        rotate_all_logs_on_startup=lambda: None,
        signal_handler=lambda sig, frame: None,
        set_rate_limit_config=lambda cfg: None,
        log_info=lambda *a, **k: None,
    )

    # Stop before the event loop: registration happens during config
    # assembly, and running the server would block the test.
    class _Stop(Exception):
        pass

    monkeypatch.setattr("arena.cli.web.run_app", lambda *a, **k: (_ for _ in ()).throw(_Stop()))

    args = build_parser(ctx).parse_args([
        "serve", "--root", str(tmp_path), "--port", "0",
    ])
    with pytest.raises(_Stop):
        serve(args, ctx)

    assert redact_string(f"echo {startup_token}") == "echo <redacted:bridge-token>"
    assert sanitize_audit_event({"cmd": f"echo {startup_token}"})["cmd"] == (
        "echo <redacted:bridge-token>"
    )


def test_rotating_the_token_registers_the_new_one_and_drops_the_old(monkeypatch):
    """After rotation the fresh token must not leak, and the old one may."""
    from arena.observability import redact as redact_mod

    old_token = "OldRotated" + "TokenAbcdefghijklmnopqr"
    new_token = "NewRotated" + "TokenZyxwvutsrqponmlkj"

    _isolate_registry(monkeypatch, redact_mod)
    register_literal_secret(old_token, kind="bridge-token")

    # Mirror what the /v1/admin/token/regenerate handler does.
    cfg = {"token": old_token}
    result = {"ok": True, "token": new_token}
    if result.get("ok") and result.get("token"):
        register_literal_secret(result["token"], kind="bridge-token")
        unregister_literal_secret(cfg["token"])
        cfg["token"] = result["token"]

    assert redact_string(f"echo {new_token}") == "echo <redacted:bridge-token>"
    assert registered_literal_count() == 1
    # The retired value is no longer scrubbed: keeping it forever would grow
    # the registry unbounded on every rotation, and it is no longer a secret.
    assert old_token in redact_string(f"echo {old_token}")


def test_the_regenerate_handler_keeps_the_redactor_in_step():
    """Guard the wiring itself, not a copy of it.

    The test above mirrors the handler's logic; this asserts the handler
    really contains it, so deleting those two lines fails the suite instead
    of only failing in production.
    """
    import inspect

    from arena.admin import handlers

    source = inspect.getsource(handlers)
    assert "register_literal_secret(result[\"token\"]" in source
    assert "unregister_literal_secret(cfg[\"token\"])" in source


def test_serve_wires_the_registration_at_the_source():
    """Same guard for startup: the call must live next to resolve_token."""
    import inspect

    from arena import cli

    source = inspect.getsource(cli.serve)
    assert "register_literal_secret(token" in source


# --- boundaries ---------------------------------------------------------------
#
# The fast path in `redact_string` skips the regex battery below 16 chars, on
# the premise that no pattern can match a shorter string. That premise is a
# standing constraint on every future pattern, not a comment: add one that can
# match 15 characters and it silently never fires. These pin it.

_SHORTEST_MATCHES = {
    "query-credential": "?token=" + "B" * 12,        # 19
    "token-assignment": "TOKEN=" + "B" * 12,         # 18
    "arena-token-header": "X-Arena-Token:" + "B" * 12,  # 26
    "bearer": "Bearer " + "B" * 16,                   # 23
}


@pytest.mark.parametrize("kind,text", sorted(_SHORTEST_MATCHES.items()))
def test_the_shortest_real_match_is_longer_than_the_fast_path(kind, text):
    """Every pattern's minimum match must exceed the 16-char cutoff."""
    assert len(text) >= 16, f"{kind} can match below the fast path"
    assert redact_string(text) == f"<redacted:{kind}>"


@pytest.mark.parametrize("kind,text", sorted(_SHORTEST_MATCHES.items()))
def test_one_character_below_the_minimum_is_not_a_match(kind, text):
    """Positive control: the fixtures above are minimal, not padded.

    Without this, `_SHORTEST_MATCHES` could drift to comfortable long values
    and stop testing the boundary at all.
    """
    shortened = text[:-1]
    assert redact_string(shortened) == shortened


def test_the_fast_path_cutoff_is_the_documented_value():
    """Pin the constant: raising it would silently disable short patterns.

    16 is not arbitrary -- it is below the 18-character minimum of the
    shortest pattern. A mutant that changes it to 17 keeps the suite green
    only if nothing asserts the value.
    """
    import inspect

    from arena.observability import redact as redact_mod

    source = inspect.getsource(redact_mod.redact_string)
    assert "if len(text) < 16:" in source
    shortest = min(len(t) for t in _SHORTEST_MATCHES.values())
    assert shortest > 16, (
        f"a pattern now matches at {shortest} chars, at or below the 16-char "
        "fast path -- lower the cutoff or the pattern will never fire"
    )


def test_the_minimum_literal_length_is_the_documented_value():
    """A literal at exactly the limit registers; one below does not."""
    assert LITERAL_MIN_LENGTH == 12
    at_limit = "L" * LITERAL_MIN_LENGTH
    below = "L" * (LITERAL_MIN_LENGTH - 1)
    assert register_literal_secret(at_limit, kind="test-secret") is True
    try:
        assert register_literal_secret(below) is False
        assert redact_string(at_limit) == "<redacted:test-secret>"
    finally:
        unregister_literal_secret(at_limit)


def test_the_default_kind_is_the_bridge_token():
    """The marker tells the operator which credential to rotate."""
    probe = "DefaultKind" + "ProbeAbcdefghij"
    assert register_literal_secret(probe) is True
    try:
        assert redact_string(probe) == "<redacted:bridge-token>"
    finally:
        unregister_literal_secret(probe)


def test_the_marker_format_is_exactly_the_documented_one():
    """`<redacted:kind>` with no padding: log scrapers match on it."""
    assert redact_string("Bearer " + "B" * 16) == "<redacted:bearer>"
    probe = "MarkerFormat" + "ProbeAbcdefghij"
    register_literal_secret(probe, kind="probe-kind")
    try:
        assert redact_string(f"x {probe} y") == "x <redacted:probe-kind> y"
    finally:
        unregister_literal_secret(probe)


# --- review round 2: defects the bots found and live probes confirmed --------
#
# Every test below was written against a reproduction, not against the
# review text. Codacy's thread-safety note and three Qodo findings were
# each replayed in-process first; the fourth (fixture shape) was proved
# by gitleaks failing this PR's own Security job.


def test_the_literal_scan_survives_rotation_on_another_thread():
    """Reproduction: `RuntimeError: dictionary changed size during iteration`.

    The bridge runs blocking work (`token_regenerate`, shell execs) on an
    executor, so a rotation lands on a different thread than the audit
    write. Iterating the registry dict directly raised -- and it raised
    inside the redactor, i.e. the audit record for a token rotation was
    exactly the one most likely to be lost.
    """
    import threading

    stop = threading.Event()
    errors: list[str] = []

    def rotate() -> None:
        i = 0
        while not stop.is_set():
            value = f"rotating-literal-{i:030d}"
            register_literal_secret(value)
            unregister_literal_secret(value)
            i += 1

    def read() -> None:
        try:
            for _ in range(50_000):
                redact_string("an ordinary audit field with some text in it")
        except Exception as exc:  # noqa: BLE001 - any raise is the defect
            errors.append(f"{type(exc).__name__}: {exc}")

    writer = threading.Thread(target=rotate, daemon=True)
    reader = threading.Thread(target=read)
    writer.start()
    reader.start()
    reader.join(timeout=60)
    stop.set()
    writer.join(timeout=10)

    assert errors == [], f"redact_string raised during concurrent rotation: {errors}"


def test_a_registered_literal_is_still_scrubbed_after_a_concurrent_rotation():
    """Liveness half of the above: the snapshot must not go stale."""
    import threading

    kept = "KeptDuringRotation" + "Abcdefghijklmnop"
    register_literal_secret(kept, kind="bridge-token")
    stop = threading.Event()

    def churn() -> None:
        i = 0
        while not stop.is_set():
            value = f"churn-literal-{i:030d}"
            register_literal_secret(value)
            unregister_literal_secret(value)
            i += 1

    writer = threading.Thread(target=churn, daemon=True)
    writer.start()
    try:
        for _ in range(2000):
            assert kept not in redact_string(f"echo {kept}")
    finally:
        stop.set()
        writer.join(timeout=10)
        unregister_literal_secret(kept)


def test_a_longer_literal_wins_over_a_shorter_one_it_contains():
    """Longest-first ordering: otherwise the longer token is left half-masked."""
    short = "ShortLiteralAbc" + "defghij"
    longer = short + "AndThenSomeMore"
    register_literal_secret(short, kind="short-secret")
    register_literal_secret(longer, kind="long-secret")
    try:
        assert redact_string(f"echo {longer}") == "echo <redacted:long-secret>"
        assert redact_string(f"echo {short}") == "echo <redacted:short-secret>"
    finally:
        unregister_literal_secret(short)
        unregister_literal_secret(longer)


# --- CLI option spellings (`--token V` / `--token=V`) ------------------------
#
# The bridge's own CLI takes the master token this way, so an audited
# command that starts or manages a PEER bridge carries a credential this
# process has never registered. Only a pattern can catch those.

@pytest.mark.parametrize("cmd", [
    "arena serve --token PeerBridgeTokenAbcdefghijklmnop",
    "arena serve --token=PeerBridgeTokenAbcdefghijklmnop",
    "arena serve --token 'PeerBridgeTokenAbcdefghijklmnop'",
    'arena serve --token "PeerBridgeTokenAbcdefghijklmnop"',
    "arena serve --api-key PeerBridgeTokenAbcdefghijklmnop",
    "arena serve --password PeerBridgeTokenAbcdefghijklmnop",
])
def test_an_unregistered_peer_token_on_the_command_line_is_scrubbed(cmd):
    out = redact_string(cmd)
    assert "PeerBridgeToken" not in out, out
    assert "<redacted:cli-credential-option>" in out, out


def test_the_cli_option_pattern_does_not_eat_ordinary_flags():
    """Reverse sabotage: a non-credential flag must survive untouched."""
    cmd = "arena serve --port 8765 --profile developer --root /var/lib/arena"
    assert redact_string(cmd) == cmd


def test_a_github_pat_after_token_keeps_its_own_marker():
    """Specific-before-generic: the marker says which credential to rotate."""
    pat = "ghp" + "_" + "1234567890abcdefghijklmnopqrstuvwxYZ"
    out = redact_string(f"arena serve --token {pat}")
    assert "<redacted:github>" in out, out


# --- percent-encoded query credentials ---------------------------------------
#
# The query auth path percent-decodes before comparing, so
# `?token=correct%20horse%20battery%20staple` authenticates as the
# decoded value. Literal substitution searches for the decoded secret
# and therefore cannot see the encoded spelling.

@pytest.mark.parametrize("url,secret", [
    ("curl 'http://127.0.0.1:8765/v1/status?token=correct%20horse%20battery%20staple'",
     "correct%20horse"),
    ("curl 'http://127.0.0.1:8765/v1/status?api_key=pass%2Fword%2Bwith%3Descapes'",
     "pass%2Fword"),
    ("curl 'http://127.0.0.1:8765/v1/exec?access_token=%41%42%43%44%45%46%47%48%49%4A%4B%4C'",
     "%41%42%43"),
])
def test_a_percent_encoded_query_credential_is_scrubbed(url, secret):
    out = redact_string(url)
    assert secret not in out, out
    assert "<redacted:query-credential>" in out, out


def test_the_query_pattern_leaves_ordinary_encoded_parameters_alone():
    """Reverse sabotage: only credential-named parameters are touched."""
    url = "curl 'http://127.0.0.1:8765/v1/fs/read?path=C%3A%5CUsers%5CIvan%5Cnotes.txt'"
    assert redact_string(url) == url


def test_the_decoded_form_of_a_registered_token_is_still_scrubbed():
    """The literal registry covers the decoded spelling; both must hold."""
    spaced = "correct horse battery staple"
    register_literal_secret(spaced, kind="bridge-token")
    try:
        out = redact_string(f"curl 'http://127.0.0.1:8765/v1/status?token={spaced}'")
        assert "correct" not in out, out
    finally:
        unregister_literal_secret(spaced)


# --- a master token too short to protect -------------------------------------

def test_serve_refuses_to_start_on_a_token_it_cannot_redact(monkeypatch, tmp_path):
    """A bridge that cannot scrub its own bearer must not serve.

    `--token` and ARENA_LOCAL_BRIDGE_TOKEN had no minimum length (the
    token *file* path enforces 16), so a 9-character token authenticated
    requests while being too short to register -- and went to the audit
    log in the clear. Registration failure was ignored at startup.
    """
    from aiohttp import web

    from arena.cli import CliContext, serve
    from arena.observability import redact as redact_mod

    _isolate_registry(monkeypatch, redact_mod)
    short_token = "hunter2xy"
    assert len(short_token) < LITERAL_MIN_LENGTH

    started: list[str] = []

    ctx = CliContext(
        version="test-version",
        audit_path=tmp_path / "audit.jsonl",
        default_max_output=123,
        default_max_concurrent=4,
        cdp_state={},
        make_app=lambda cfg: web.Application(),
        resolve_token=lambda token: (short_token, tmp_path / "token.txt"),
        token_generator=lambda: "generated-token",
        daemonize=lambda: None,
        ensure_session_env=lambda: None,
        load_config_file=lambda: {},
        rotate_all_logs_on_startup=lambda: None,
        signal_handler=lambda sig, frame: None,
        set_rate_limit_config=lambda cfg: None,
        log_info=lambda *a, **k: None,
    )

    monkeypatch.setattr(
        "arena.cli.web.run_app", lambda *a, **k: started.append("ran")
    )

    args = build_parser(ctx).parse_args([
        "serve", "--root", str(tmp_path), "--port", "0",
    ])
    with pytest.raises(SystemExit) as excinfo:
        serve(args, ctx)

    assert started == [], "the bridge served with an unprotectable master token"
    message = str(excinfo.value)
    assert str(LITERAL_MIN_LENGTH) in message, message
    assert "audit" in message.lower(), message


def _call_token_regenerate(monkeypatch, tmp_path, cfg, fake_result):
    """Drive the real POST /v1/token/regenerate handler.

    Earlier revisions of these tests re-implemented the handler's five
    lines inline. That is a test of the copy, not of the code: sabotaging
    the real handler left them green. Always go through
    `make_admin_handlers`.
    """
    import asyncio

    import unified_bridge as ub
    from arena.admin.handlers import make_admin_handlers
    from arena.app_keys import APP_CFG
    from arena.handler_context import AdminHandlerContext

    monkeypatch.setattr(
        "arena.admin.handlers.token_regenerate",
        lambda *a, **k: dict(fake_result),
    )

    ctx = AdminHandlerContext(
        require_auth=lambda request: None,  # falsy == authorised; see handler_helpers.authed
        record_request=lambda *a, **k: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        audit=lambda event: None,
        default_token_file=tmp_path / "token.txt",
        root_agent=tmp_path,
        subprocess_kwargs=ub._subprocess_kwargs,
    )
    handlers = make_admin_handlers(ctx)

    class _Request:
        def __init__(self) -> None:
            self.app = {APP_CFG: cfg}
            self.headers = {}
            self.method = "POST"
            self.path = "/v1/token/regenerate"

        def __getitem__(self, key):
            raise KeyError(key)

        def __setitem__(self, key, value):
            pass

    asyncio.run(handlers.token_regenerate(_Request()))
    return cfg


def test_rotation_keeps_the_old_literal_when_the_new_one_cannot_register(
    monkeypatch, tmp_path,
):
    """Never end a rotation with neither token protected."""
    from arena.observability import redact as redact_mod

    _isolate_registry(monkeypatch, redact_mod)
    old_token = "StillProtected" + "TokenAbcdefghijkl"
    register_literal_secret(old_token, kind="bridge-token")

    cfg = {"token": old_token, "token_file": str(tmp_path / "token.txt")}
    _call_token_regenerate(
        monkeypatch, tmp_path, cfg, {"ok": True, "token": "short"},
    )

    assert old_token not in redact_string(f"echo {old_token}"), (
        "rotation dropped the old literal for a token too short to register"
    )
    assert redact_mod.registered_literal_count() >= 1


def test_rotation_through_the_real_handler_protects_the_new_token(
    monkeypatch, tmp_path,
):
    """The happy path, driven end-to-end rather than re-implemented."""
    from arena.observability import redact as redact_mod

    _isolate_registry(monkeypatch, redact_mod)
    old_token = "HandlerOld" + "TokenAbcdefghijklmn"
    new_token = "HandlerNew" + "TokenZyxwvutsrqponm"
    register_literal_secret(old_token, kind="bridge-token")

    cfg = {"token": old_token, "token_file": str(tmp_path / "token.txt")}
    _call_token_regenerate(
        monkeypatch, tmp_path, cfg, {"ok": True, "token": new_token},
    )

    assert cfg["token"] == new_token
    assert redact_string(f"echo {new_token}") == "echo <redacted:bridge-token>"
    # The superseded token no longer needs protecting and must not linger.
    assert old_token in redact_string(f"echo {old_token}")


def test_the_snapshot_is_usable_before_anything_is_registered():
    """A fresh import must be iterable, not None.

    The reader does no None-guard on purpose -- iterating an empty tuple
    is the cheap case -- so the module-level initial value is
    load-bearing. Asserted in a subprocess: in-process the value has
    already been rebuilt by every earlier test that registered a
    literal, which would make this pass no matter what it is initialised
    to.
    """
    import subprocess

    program = (
        "from arena.observability.redact import redact_string, _LITERAL_SNAPSHOT;"
        "assert isinstance(_LITERAL_SNAPSHOT, tuple), type(_LITERAL_SNAPSHOT);"
        "assert redact_string('plain text, nothing secret at all here') =="
        " 'plain text, nothing secret at all here'"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "redact_string is broken on a freshly imported module:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_redaction_works_on_a_registry_that_was_never_touched(monkeypatch):
    """Same guarantee, driven through the public API on a clean registry."""
    from arena.observability import redact as redact_mod

    _isolate_registry(monkeypatch, redact_mod)
    assert redact_mod.registered_literal_count() == 0
    assert redact_string("Bearer " + "B" * 16) == "<redacted:bearer>"
