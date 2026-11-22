"""#525: callers who share an address (a tunnel, a reverse proxy) do not share one request budget with the token holder."""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import arena.rate_limit as rl
import unified_bridge as ub

LIMIT = 5
OWNER = "owner-525"
ROLES = {OWNER: (True, "admin"), "user-525": (True, "user")}


class _Request:
    """What the limiter reads from a request: the address and, through the probe, the token."""

    def __init__(self, token: str = "", remote: str | None = "127.0.0.1"):
        self.remote = remote
        self.token = token


def _role(request: _Request) -> tuple[bool, str]:
    return ROLES.get(request.token, (False, ""))


def _refusal(body: dict, status: int = 200) -> web.Response:
    return web.json_response(body, status=status)


def _hit(token: str = "", remote: str | None = "127.0.0.1") -> int:
    """Status the limiter answers with; 200 stands for 'let through'."""
    refused = rl.check_rate_limit(_Request(token, remote), cors_json_response_fn=_refusal, check_auth_with_role_fn=_role)
    return refused.status if refused is not None else 200


@pytest.fixture(name="small_limit", autouse=True)
def _small_limit(monkeypatch):
    """Five requests a minute and empty counts, restored afterwards."""
    monkeypatch.setattr(rl, "_rate_limit_max", LIMIT)
    monkeypatch.setattr(rl, "_rate_limit_store", {})
    monkeypatch.setattr(rl, "_rl_v2_store", {})


def test_a_flood_without_a_token_leaves_the_token_holder_served():
    """The case from the issue: a scanner behind the same tunnel."""
    assert [_hit() for _ in range(LIMIT + 3)] == [200] * LIMIT + [429] * 3
    assert _hit(OWNER) == 200


def test_a_flood_with_a_wrong_token_is_counted_with_the_anonymous_callers():
    """Presenting something is not the same as holding a token."""
    assert [_hit("a-guess") for _ in range(LIMIT + 1)] == [200] * LIMIT + [429]
    assert _hit() == 429
    assert _hit(OWNER) == 200


def test_the_token_holder_is_still_limited():
    """A separate count, not an exemption."""
    assert [_hit(OWNER) for _ in range(LIMIT + 1)] == [200] * LIMIT + [429]
    assert _hit() == 200


def test_roles_are_counted_apart_and_addresses_still_matter():
    """One role's requests do not use up another's, nor another address's."""
    assert [_hit(OWNER) for _ in range(LIMIT + 1)][-1] == 429
    assert _hit("user-525") == 200
    assert _hit(OWNER, remote="10.0.0.7") == 200


def test_anonymous_callers_keep_the_bare_address_as_their_key():
    """Their count is where it was before, including for a request with no address."""
    _hit()
    _hit(remote=None)
    assert sorted(rl._rate_limit_store) == ["127.0.0.1", "anonymous"]


def test_without_a_probe_everyone_at_an_address_is_counted_together():
    """A caller of the limiter that passes no probe gets the earlier behaviour."""
    for _ in range(LIMIT):
        assert rl.check_rate_limit(_Request(), cors_json_response_fn=_refusal) is None
    assert rl.check_rate_limit(_Request(OWNER), cors_json_response_fn=_refusal).status == 429


async def _flood_then_ask(root: str, paths: list[str]) -> tuple[list[int], int]:
    app = ub.make_app({"token": OWNER, "profile": "owner-shell", "root": root, "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    async with TestClient(TestServer(app)) as client:
        flood = [(await client.get(path)).status for path in paths]
        answer = await client.get("/v1/version", headers={"Authorization": f"Bearer {OWNER}"})
        return flood, answer.status


def test_the_running_bridge_serves_its_owner_through_a_scan(tmp_path):
    """End to end: the middleware hands the limiter the probe."""
    flood, owner = asyncio.run(_flood_then_ask(str(tmp_path), [f"/secrets-{number}.env" for number in range(LIMIT + 3)]))
    assert flood == [404] * LIMIT + [429] * 3
    assert owner == 200
