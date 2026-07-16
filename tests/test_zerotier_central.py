"""Unit tests for arena.admin.zerotier_central (v3.96.0).

Every test that would hit the network monkeypatches
``urllib.request.urlopen`` inside the module, so the suite runs
offline and deterministically.
"""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin import zerotier_central as ztc  # noqa: E402


class _FakeResp:
    def __init__(self, status: int, body: object):
        self.status = status
        if isinstance(body, (dict, list)):
            self._data = json.dumps(body).encode()
        else:
            self._data = (body or "").encode() if isinstance(body, str) else b""

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake(monkeypatch, status=200, body=None, exc=None, capture=None):
    """Replace urlopen in the module. `capture` is a list that will
    receive (method, url, body_bytes) for each call so tests can
    inspect what was sent."""
    def fake_urlopen(req, timeout=15):
        if capture is not None:
            b = None
            try:
                b = req.data
            except Exception:
                pass
            capture.append({
                "method": req.get_method(),
                "url": req.full_url,
                "body": json.loads(b.decode()) if b else None,
                "headers": dict(req.headers),
            })
        if exc is not None:
            raise exc
        return _FakeResp(status, body)
    monkeypatch.setattr(ztc.urllib.request, "urlopen", fake_urlopen)


# --- token discovery -----------------------------------------------------

def test_read_token_from_env(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "  abcXYZ  ")
    tok, src = ztc.read_central_token()
    assert tok == "abcXYZ"
    assert src.startswith("env:")


def test_read_token_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN", raising=False)
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN_FILE", raising=False)
    f = tmp_path / "tok"
    f.write_text("mytoken123\nignored\n")
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN_FILE", str(f))
    tok, src = ztc.read_central_token()
    assert tok == "mytoken123"
    assert str(f) in src


def test_read_token_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN", raising=False)
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN_FILE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    tok, reason = ztc.read_central_token()
    assert tok is None
    assert "no token" in reason.lower()


def test_no_token_response_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN", raising=False)
    monkeypatch.delenv("ZEROTIER_CENTRAL_TOKEN_FILE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    r = ztc.list_networks()
    assert r["ok"] is False
    assert "not configured" in r["error"]
    assert "hint" in r


# --- request wire-format -------------------------------------------------

def test_bearer_header_and_useragent(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body=[], capture=cap)
    ztc.list_networks()
    assert len(cap) == 1
    # Header casing depends on urllib normalisation; check both.
    h = {k.lower(): v for k, v in cap[0]["headers"].items()}
    assert h.get("authorization") == "Bearer xyz"
    assert "arena" in (h.get("user-agent") or "").lower()


# --- list_networks -------------------------------------------------------

def test_list_networks_summarises(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    _install_fake(monkeypatch, status=200, body=[
        {
            "id": "1234567890abcdef",
            "description": "test-net",
            "totalMemberCount": 3,
            "authorizedMemberCount": 2,
            "creationTime": 1234567890000,
            "lastModified": 1234567900000,
            "config": {
                "name": "hometeam",
                "private": True,
                "v4AssignMode": {"zt": True},
                "ipAssignmentPools": [{"ipRangeStart": "10.99.0.1", "ipRangeEnd": "10.99.0.254"}],
            },
        },
    ])
    r = ztc.list_networks()
    assert r["ok"] is True
    assert r["count"] == 1
    n = r["networks"][0]
    assert n["id"] == "1234567890abcdef"
    assert n["name"] == "hometeam"
    assert n["member_count"] == 3
    assert n["authorized_count"] == 2
    assert n["private"] is True
    assert n["ip_pools"][0]["ipRangeStart"] == "10.99.0.1"


def test_list_networks_upstream_401(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    import urllib.error
    err = urllib.error.HTTPError(
        "https://api.zerotier.com/api/v1/network", 401, "Unauthorized",
        {}, BytesIO(b'{"message":"invalid token"}'),
    )
    _install_fake(monkeypatch, exc=err)
    r = ztc.list_networks()
    assert r["ok"] is False
    assert r["status"] == 401
    assert "invalid token" in r["error"]


# --- create_network ------------------------------------------------------

def test_create_network_requires_name(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    r = ztc.create_network("")
    assert r["ok"] is False
    assert "name required" in r["error"]


def test_create_network_success(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body={
        "id": "abcdef0123456789", "config": {"name": "n1"},
    }, capture=cap)
    r = ztc.create_network("n1")
    assert r["ok"] is True
    assert r["network"]["id"] == "abcdef0123456789"
    # Payload has config.name set.
    assert cap[0]["body"]["config"]["name"] == "n1"


def test_create_network_merges_extra_config(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body={"id": "0000000000000000"},
                  capture=cap)
    extra = {"config": {"private": False, "ipAssignmentPools": [
        {"ipRangeStart": "10.5.0.10", "ipRangeEnd": "10.5.0.20"}
    ]}}
    ztc.create_network("mynet", extra)
    sent = cap[0]["body"]
    assert sent["config"]["name"] == "mynet"
    assert sent["config"]["private"] is False
    assert sent["config"]["ipAssignmentPools"][0]["ipRangeStart"] == "10.5.0.10"


# --- delete_network + validation ----------------------------------------

def test_delete_network_bad_id():
    r = ztc.delete_network("nope")
    assert r["ok"] is False
    assert "16 hex" in r["error"]


def test_delete_network_success(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body="", capture=cap)
    r = ztc.delete_network("ABCDEF0123456789")
    assert r["ok"] is True
    assert r["network_id"] == "abcdef0123456789"
    assert cap[0]["method"] == "DELETE"
    assert cap[0]["url"].endswith("/network/abcdef0123456789")


# --- list_members / update / delete -------------------------------------

def test_list_members_bad_id():
    r = ztc.list_members("shortid")
    assert r["ok"] is False
    assert "16 hex" in r["error"]


def test_list_members_summarises(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    _install_fake(monkeypatch, status=200, body=[
        {"nodeId": "aabbccddee", "name": "workstation", "hidden": False,
         "physicalAddress": "203.0.113.5",
         "clientVersion": "1.16.2", "lastOnline": 1700000000000,
         "config": {"authorized": True, "ipAssignments": ["10.99.0.5"]}},
        {"nodeId": "1122334455", "name": "", "hidden": False,
         "physicalAddress": "", "clientVersion": "1.16.2",
         "lastOnline": 1699999000000,
         "config": {"authorized": False, "ipAssignments": []}},
    ])
    r = ztc.list_members("0123456789abcdef")
    assert r["ok"] is True
    assert r["count"] == 2
    assert r["authorized_count"] == 1
    assert r["members"][0]["node_id"] == "aabbccddee"
    assert r["members"][0]["authorized"] is True


def test_update_member_bad_ids():
    r = ztc.update_member("bad", "alsoBad")
    assert r["ok"] is False


def test_update_member_requires_change(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    r = ztc.update_member("0123456789abcdef", "aabbccddee")
    assert r["ok"] is False
    assert "nothing to update" in r["error"]


def test_update_member_authorize(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body={"nodeId": "aabbccddee",
                  "config": {"authorized": True}}, capture=cap)
    r = ztc.update_member("0123456789abcdef", "AABBCCDDEE",
                          authorized=True, name="lab-workstation",
                          ip_assignments=["10.99.0.5"])
    assert r["ok"] is True
    body = cap[0]["body"]
    assert body["config"]["authorized"] is True
    assert body["config"]["ipAssignments"] == ["10.99.0.5"]
    assert body["name"] == "lab-workstation"
    # Node ID normalised to lowercase in URL.
    assert cap[0]["url"].endswith("/network/0123456789abcdef/member/aabbccddee")


def test_delete_member_success(monkeypatch):
    monkeypatch.setenv("ZEROTIER_CENTRAL_TOKEN", "xyz")
    cap = []
    _install_fake(monkeypatch, status=200, body="", capture=cap)
    r = ztc.delete_member("0123456789abcdef", "aabbccddee")
    assert r["ok"] is True
    assert cap[0]["method"] == "DELETE"


# --- routes + wiring registration ---------------------------------------

def test_zerotier_central_routes_in_registry():
    """v3.96.0: routes are registered in the canonical registry."""
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    expected = {
        ("GET", "/v1/zerotier/central/status"),
        ("GET", "/v1/zerotier/central/networks"),
        ("POST", "/v1/zerotier/central/networks"),
        ("GET", "/v1/zerotier/central/networks/{nwid}"),
        ("DELETE", "/v1/zerotier/central/networks/{nwid}"),
        ("GET", "/v1/zerotier/central/networks/{nwid}/members"),
        ("POST", "/v1/zerotier/central/networks/{nwid}/members/{node}"),
        ("DELETE", "/v1/zerotier/central/networks/{nwid}/members/{node}"),
    }
    missing = expected - keys
    assert not missing, f"missing routes: {missing}"


def test_zerotier_central_routes_wired_into_app():
    import asyncio
    import unified_bridge as ub
    app = ub.make_app({
        "token": "test", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("GET", "/v1/zerotier/central/status") in paths
    assert ("POST", "/v1/zerotier/central/networks") in paths
    assert ("DELETE", "/v1/zerotier/central/networks/{nwid}/members/{node}") in paths
