"""One admin request must not repoint updates for the whole process (#361).

`/v1/admin/update/check` accepts an optional `{"repo": ...}` override.
It used to deliver it by assigning to `os.environ["ARENA_UPDATE_REPO"]`,
which `auto_update._repo()` reads. `os.environ` is process-wide and the
write was never undone, so a single request changed where *every* later
caller looked for releases -- including requests that asked for nothing,
and including the `/update/status` endpoint that reports the repository
to the dashboard as if it were configuration.

`ARENA_UPDATE_REPO` is classified `security` in SECURITY.md ("Redirects
the repository used for self-update metadata and artifacts"), so this
was a security-relevant setting mutable by one request and sticky
afterwards.

Found while fixing #348: it was the one `ARENA_*` value leaking out of
the test suite that no test was setting.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import pytest

from arena.admin import auto_update as au
from arena.admin.handlers_update import make_update_handlers
from tests.test_handlers_update_parity_v4_169_39 import _make_req, _MockContext

_UNCHANGED = {"ok": True, "current": "1.0", "latest": "1.0", "needs_update": False}


@pytest.fixture
def handlers(monkeypatch):
    monkeypatch.delenv("ARENA_UPDATE_REPO", raising=False)
    return make_update_handlers(_MockContext())


def _post_check(handlers, body):
    return asyncio.run(handlers["update_check"](
        _make_req("POST", "/v1/admin/update/check", body)))


def test_an_override_does_not_outlive_the_request_that_carried_it(
        handlers) -> None:
    """The defect itself: the override used to be permanent and global."""
    with patch("arena.admin.auto_update.check_updates", return_value=_UNCHANGED):
        assert _post_check(handlers, {"repo": "attacker/evil-fork"}).status == 200

    assert os.environ.get("ARENA_UPDATE_REPO") is None, (
        "a request-scoped parameter was written into the process environment")
    assert au._repo() == au.DEFAULT_REPO


def test_a_later_request_that_asks_for_nothing_gets_the_configured_repo(
        handlers) -> None:
    """The consequence that made it a defect rather than an oddity.

    A second, unrelated request -- no `repo` in its body at all --
    inherited the first one's override, because the only channel
    between the handler and the checker was process-wide state.
    """
    seen: list[str | None] = []

    def record(*, current_version=None, repo=None):
        seen.append(repo)
        return _UNCHANGED

    with patch("arena.admin.auto_update.check_updates", side_effect=record):
        _post_check(handlers, {"repo": "attacker/evil-fork"})
        _post_check(handlers, {})

    assert seen == ["attacker/evil-fork", None], (
        "the second request inherited the first request's override")


def test_the_status_endpoint_does_not_report_an_override_as_configuration(
        handlers) -> None:
    """`/update/status` reports the repo the dashboard shows the operator.

    While the override lived in `os.environ` it was indistinguishable
    from deployment configuration, so the dashboard confirmed the
    attacker-supplied repository back to the operator as the current
    setting.
    """
    with patch("arena.admin.auto_update.check_updates", return_value=_UNCHANGED):
        _post_check(handlers, {"repo": "attacker/evil-fork"})

    resp = asyncio.run(handlers["update_status"](
        _make_req("GET", "/v1/admin/update/status", None)))

    assert json.loads(resp.text)["repo"] == au.DEFAULT_REPO


def test_the_override_still_reaches_the_checker_for_its_own_request(
        handlers) -> None:
    """The control: scoping it must not mean dropping it.

    Without this, every assertion above is satisfied by a handler that
    ignores `repo` entirely -- which would silently break the documented
    request body rather than fix it.
    """
    seen: list[str | None] = []

    def record(*, current_version=None, repo=None):
        seen.append(repo)
        return _UNCHANGED

    with patch("arena.admin.auto_update.check_updates", side_effect=record):
        _post_check(handlers, {"repo": "custom/repo-test "})

    assert seen == ["custom/repo-test"], "the override was dropped, not scoped"


@pytest.mark.parametrize("body", [{}, {"repo": None}, {"repo": ""}, {"repo": "   "}])
def test_an_absent_override_is_not_turned_into_a_repository_name(
        handlers, body) -> None:
    """Blank must mean "not supplied", not a repository called `""`."""
    seen: list[str | None] = []

    def record(*, current_version=None, repo=None):
        seen.append(repo)
        return _UNCHANGED

    with patch("arena.admin.auto_update.check_updates", side_effect=record):
        _post_check(handlers, body)

    assert seen == [None]


def test_the_environment_variable_still_configures_the_repository(
        monkeypatch) -> None:
    """`ARENA_UPDATE_REPO` stays supported as deployment configuration.

    Only the request-scoped path stopped going through it; operators
    setting it in the bridge's environment are unaffected.
    """
    monkeypatch.setenv("ARENA_UPDATE_REPO", "operator/configured")

    assert au._repo() == "operator/configured"
    assert au._repo(None) == "operator/configured"
    assert au._repo("   ") == "operator/configured", (
        "a blank override must fall back to configuration, not blank out the repo")
    assert au._repo("call/scoped") == "call/scoped", (
        "an explicit override must win over the ambient configuration")


def test_pick_asset_stays_a_working_monkeypatch_hook(monkeypatch) -> None:
    """Moving code must not turn a patch point into decoration.

    `auto_update._pick_asset` is patched by existing tests to control
    asset selection. Extracting the API shaper into `update_github`
    left that alias re-exported but unused, so patches on it were
    silently ignored while the import still looked right -- caught in
    review, reproduced here before fixing.
    """
    api = {"tag_name": "v9.9.9", "assets": [
        {"name": "arena-agent-v9.9.9.zip",
         "browser_download_url": "https://example/v.zip",
         "size": 5, "digest": "sha256:ab"}]}
    chosen = {"name": "chosen-by-the-patch", "browser_download_url": "https://example/p.zip",
              "size": 1, "digest": "sha256:cd"}

    monkeypatch.setattr(au, "_github_token", lambda: "token")
    monkeypatch.setattr(au, "_http_get_json", lambda url: api)
    monkeypatch.setattr(au, "_pick_asset", lambda assets: chosen)

    result = au.check_updates(current_version="1.0.0")

    assert result["asset_name"] == "chosen-by-the-patch", (
        "check_updates ignored the patched _pick_asset, so the alias is "
        "decoration rather than the documented hook")
