"""Tests for v3.86.0: multi-agent sessions.

Covers the registry, token derivation, and the auth-runtime patch --
all the surface area an operator interacts with, without spinning up
an aiohttp app.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_registry():
    from arena.multiagent import agents as ag
    ag.reset()
    yield
    ag.reset()


# ---------------------------------------------------------------------------
# Token derivation + lookup
# ---------------------------------------------------------------------------
def test_create_returns_record_with_derived_token():
    from arena.multiagent import agents as ag
    rec = ag.create(label="laptop-agent", master_token="master-42")
    assert rec.label == "laptop-agent"
    assert rec.agent_id and len(rec.agent_id) == 8
    assert rec.token.startswith("agent-" + rec.agent_id + "-")
    assert rec.request_count == 0


def test_resolve_token_returns_record_and_none_for_junk():
    from arena.multiagent import agents as ag
    rec = ag.create(label="x", master_token="master")
    same = ag.resolve_token(rec.token)
    assert same is rec
    assert ag.resolve_token("agent-nope-xxx") is None
    assert ag.resolve_token("random-string") is None
    assert ag.resolve_token("") is None


def test_looks_like_agent_token_prefix_check():
    from arena.multiagent import agents as ag
    assert ag.looks_like_agent_token("agent-abc-def") is True
    assert ag.looks_like_agent_token("Bearer x") is False
    assert ag.looks_like_agent_token("") is False


def test_derived_token_changes_when_master_rotates():
    from arena.multiagent.agents import _derive_agent_token
    a = _derive_agent_token("master-v1", "abc12345")
    b = _derive_agent_token("master-v2", "abc12345")
    assert a != b
    # But stable for the same inputs.
    a2 = _derive_agent_token("master-v1", "abc12345")
    assert a == a2


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------
def test_revoke_removes_agent_and_invalidates_token():
    from arena.multiagent import agents as ag
    rec = ag.create(label="x", master_token="master")
    assert ag.revoke(rec.agent_id) is True
    assert ag.get(rec.agent_id) is None
    assert ag.resolve_token(rec.token) is None
    # Revoking twice is a no-op returning False.
    assert ag.revoke(rec.agent_id) is False


# ---------------------------------------------------------------------------
# Multi-agent isolation
# ---------------------------------------------------------------------------
def test_two_agents_get_distinct_ids_and_tokens():
    from arena.multiagent import agents as ag
    a = ag.create(label="alice", master_token="master")
    b = ag.create(label="bob",   master_token="master")
    assert a.agent_id != b.agent_id
    assert a.token != b.token
    assert {r.agent_id for r in ag.list_agents()} == {a.agent_id, b.agent_id}


def test_note_request_and_audit_recording_are_per_agent():
    from arena.multiagent import agents as ag
    a = ag.create(label="a", master_token="m")
    b = ag.create(label="b", master_token="m")
    ag.note_request(a.agent_id)
    ag.note_request(a.agent_id)
    ag.note_request(b.agent_id)
    ag.record_audit(a.agent_id, {"type": "shell", "cmd": "ls"})
    ag.record_audit(b.agent_id, {"type": "shell", "cmd": "pwd"})
    ra = ag.get(a.agent_id); rb = ag.get(b.agent_id)
    assert ra.request_count == 2
    assert rb.request_count == 1
    assert len(ra.audit_ring) == 1 and ra.audit_ring[0]["cmd"] == "ls"
    assert len(rb.audit_ring) == 1 and rb.audit_ring[0]["cmd"] == "pwd"


def test_audit_ring_is_bounded():
    from arena.multiagent import agents as ag
    from arena.multiagent.agents import _AUDIT_RING_SIZE
    rec = ag.create(label="x", master_token="m")
    for i in range(_AUDIT_RING_SIZE + 50):
        ag.record_audit(rec.agent_id, {"type": "x", "i": i})
    assert len(rec.audit_ring) == _AUDIT_RING_SIZE
    # Latest entries kept, oldest dropped.
    assert rec.audit_ring[-1]["i"] == _AUDIT_RING_SIZE + 49
    assert rec.audit_ring[0]["i"] == 50


# ---------------------------------------------------------------------------
# Snapshot never leaks the token unless explicitly asked.
# ---------------------------------------------------------------------------
def test_snapshot_hides_token_by_default():
    from arena.multiagent import agents as ag
    rec = ag.create(label="x", master_token="m")
    default_snap = ag.snapshot(rec)
    assert "token" not in default_snap
    with_token = ag.snapshot(rec, include_token=True)
    assert with_token["token"] == rec.token


# ---------------------------------------------------------------------------
# Label sanitisation
# ---------------------------------------------------------------------------
def test_create_sanitises_label_and_truncates():
    from arena.multiagent import agents as ag
    rec = ag.create(label="ok\nlabel\t\x00" + "a" * 200, master_token="m")
    # Newline, tab, null replaced with '_'; length capped at 80.
    assert "\n" not in rec.label and "\x00" not in rec.label
    assert len(rec.label) <= 80


def test_create_empty_label_gets_default():
    from arena.multiagent import agents as ag
    rec = ag.create(label="", master_token="m")
    assert rec.label == "agent"


# ---------------------------------------------------------------------------
# Auth runtime integration -- agent token accepted alongside master.
# ---------------------------------------------------------------------------
class _FakeApp(dict):
    pass


class _FakeReq:
    def __init__(self, headers=None, query=None, master_token="master"):
        self.headers = headers or {}
        self.query = query or {}
        # Emulate aiohttp's Request-as-dict semantics for
        # request["agent_id"] = ... below.
        self._store: dict = {}
        from arena.app_keys import APP_CFG
        self.app = _FakeApp()
        self.app[APP_CFG] = {"token": master_token}
        self.remote = "127.0.0.1"

    def __getitem__(self, k): return self._store[k]
    def __setitem__(self, k, v): self._store[k] = v
    def __contains__(self, k): return k in self._store


def _make_runtime(tmp_users=None):
    from pathlib import Path
    from arena.auth.runtime import AuthRuntimeContext, make_auth_runtime
    from arena.auth.users import UserStore
    users_file = tmp_users or Path("/tmp/arena-test-users-nonexistent.json")
    us = UserStore(users_file)
    return make_auth_runtime(AuthRuntimeContext(
        user_store=us,
        rate_limit_lock=__import__("threading").Lock(),
        rate_limit_store={},
        cors_json_response=lambda *a, **k: None,
        log_warning=lambda *a, **k: None,
    ))


def test_check_auth_accepts_master_token_via_bearer():
    rt = _make_runtime()
    req = _FakeReq(headers={"Authorization": "Bearer master"})
    assert rt.check_auth(req) is True


def test_check_auth_accepts_agent_token_and_records_agent_id():
    from arena.multiagent import agents as ag
    rec = ag.create(label="alice", master_token="master")
    rt = _make_runtime()
    req = _FakeReq(headers={"Authorization": "Bearer " + rec.token})
    assert rt.check_auth(req) is True
    assert req["agent_id"] == rec.agent_id
    assert req["agent_label"] == "alice"
    # And note_request bumped the counter.
    assert ag.get(rec.agent_id).request_count == 1


def test_check_auth_accepts_agent_token_via_query_param():
    from arena.multiagent import agents as ag
    rec = ag.create(label="q", master_token="master")
    rt = _make_runtime()
    req = _FakeReq(query={"token": rec.token})
    assert rt.check_auth(req) is True
    assert req["agent_id"] == rec.agent_id


def test_check_auth_rejects_forged_agent_token():
    """Attacker knows the shape but not the master token -- they can't
    forge a valid derived token."""
    from arena.multiagent import agents as ag
    real = ag.create(label="real", master_token="master")
    # Same agent_id but wrong HMAC.
    forged = f"agent-{real.agent_id}-deadbeefdeadbeef"
    rt = _make_runtime()
    req = _FakeReq(headers={"Authorization": "Bearer " + forged})
    assert rt.check_auth(req) is False


def test_check_auth_rejects_revoked_agent_token():
    from arena.multiagent import agents as ag
    rec = ag.create(label="soon-gone", master_token="master")
    ag.revoke(rec.agent_id)
    rt = _make_runtime()
    req = _FakeReq(headers={"Authorization": "Bearer " + rec.token})
    assert rt.check_auth(req) is False
