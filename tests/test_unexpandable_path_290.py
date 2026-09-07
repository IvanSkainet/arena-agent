"""A path that will not expand is a 400, not a 500 (#290).

Found by the #258 fuzzing gate in the same run as #288, and it is the same
defect in a different module: the operating system's refusal arrives as an
exception, after the handler has already decided the request is fine.

`~Qm` is a tilde naming a user who does not exist, with no separator after
it. `Path.expanduser()` must produce that user's home directory, cannot,
and raises `RuntimeError: Could not determine home directory.` -- so four
endpoints answered::

    PATCH /v1/fs/edit  {"path": "~Qm"}
      -> 500 {"ok": false, "error": "RuntimeError: Could not determine home
              directory.", "error_type": "RuntimeError"}

The neighbouring spellings were always right, which is what made this easy
to miss: `~nobody/x` is a 403 (it expands, and lands outside the home),
`~/x` a 404, `~` a 404. Only the separator-less form reaches the raise.

The envelope naming a Python type is the second half of the defect, and
the one #254, #259 and #270 each spent a test pinning as absent elsewhere.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arena.files.sandbox import resolve_home_path
from tests._live_bridge import auth_header, error_type_of, json_payload, running_client

TOKEN = "unexpandable-path-token-290"

# Tilde forms that cannot expand: a user who does not exist, named without
# a separator. With a separator (`~Qm/x`) `expanduser` gives the string
# back unchanged on some platforms, so both are swept rather than assumed.
UNEXPANDABLE = ("~Qm", "~nosuchuser", "~Qm/inner", "~\U0001f600")

# Every endpoint that reads a caller-supplied path through
# `resolve_home_path`. The fuzzer found one of the four; the other three
# share the function, and a fix tested on one proves nothing about them.
PATH_ENDPOINTS = (
    ("PATCH", "/v1/fs/edit", lambda p: {"path": p, "find": "a", "replace": "b"}),
    ("POST", "/v1/fs/view", lambda p: {"path": p}),
    ("POST", "/v1/fs/create", lambda p: {"path": p, "content": "x"}),
)


@pytest.mark.parametrize("path", UNEXPANDABLE)
@pytest.mark.parametrize("method,endpoint,body", PATH_ENDPOINTS,
                         ids=[e for _, e, _ in PATH_ENDPOINTS])
def test_a_path_that_cannot_expand_is_a_4xx(
        tmp_path: Path, method: str, endpoint: str, body, path: str) -> None:
    """Refused, and refused without naming a Python exception class."""
    asyncio.run(_no_endpoint_answers_5xx(tmp_path, method, endpoint, body(path)))


async def _no_endpoint_answers_5xx(
        tmp_path: Path, method: str, endpoint: str, body: dict) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.request(
            method, endpoint, headers=auth_header(TOKEN), json=body)
        payload = await json_payload(response)

    assert response.status < 500, payload
    assert payload["ok"] is False
    assert error_type_of(payload) is None, payload
    # The message may name the exception class -- `usable_cwd` has said
    # "(OSError)" since #270 and the wording is deliberately parallel. What
    # must not survive is the raised text, which describes the bridge's own
    # machinery rather than anything the caller wrote.
    assert "Could not determine home directory" not in str(payload), payload


@pytest.mark.parametrize("path", UNEXPANDABLE)
def test_download_refuses_the_same_path(tmp_path: Path, path: str) -> None:
    """The GET half: the same function, reached through a query string."""
    asyncio.run(_download_is_a_4xx(tmp_path, path))


async def _download_is_a_4xx(tmp_path: Path, path: str) -> None:
    async with running_client(tmp_path, TOKEN) as client:
        response = await client.get(
            "/v1/download", params={"path": path}, headers=auth_header(TOKEN))
        body = await response.read()

    assert response.status < 500, body
    assert b"Could not determine home directory" not in body


@pytest.mark.parametrize("path", UNEXPANDABLE)
def test_the_resolver_refuses_without_raising(tmp_path: Path, path: str) -> None:
    """Unit half: an answer, whichever answer the local platform justifies.

    Which refusal is right depends on what `expanduser` does here. POSIX
    raises for a user with no home, so the path never becomes a path and
    the honest reply is 400. Windows has no user database to consult and
    hands the string back unchanged, so it resolves, lands outside the
    home and is a 403 -- the same 403 `~nobody/x` has always got.

    Pinning 400 everywhere would be pinning the author's platform; what
    the endpoint owes the caller is a refusal it can act on and never an
    exception, so that is what is asserted.
    """
    resolved, error, status = resolve_home_path(
        path, root=tmp_path, home=tmp_path)

    assert resolved is None
    assert status in (400, 403), (status, error)
    assert error is not None
    assert error in ("path outside home directory",) or "not a usable path" in error


def test_a_path_the_platform_cannot_expand_is_a_400(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The 400 itself, on every platform rather than only the raising ones.

    On POSIX `~Qm` produces the RuntimeError by itself; on Windows there
    is no user database to consult and the string comes back unchanged.
    Leaving the assertion to the platform would leave the guard untested
    on half of CI, so the raise is induced instead -- what matters is that
    whatever `expanduser` throws leaves as a refusal, not as a 500.
    """
    def refuses_to_expand(self: Path) -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(
        "arena.files.sandbox.Path.expanduser", refuses_to_expand, raising=True)

    resolved, error, status = resolve_home_path("~Qm", root=tmp_path, home=tmp_path)

    assert resolved is None
    assert status == 400, (status, error)
    assert error is not None and "not a usable path" in error


def test_the_forms_that_already_worked_still_work(tmp_path: Path) -> None:
    """The neighbours, pinned so the new guard does not swallow them.

    `~/x` expands into the home and is allowed; a path outside the home is
    still the 403 it was, not the new 400. Getting this wrong would turn a
    security refusal into a validation message, which is a quieter kind of
    regression than a 500 and a worse one.
    """
    inside, error, status = resolve_home_path("x", root=tmp_path, home=tmp_path)
    assert error is None and status == 200
    assert inside == tmp_path / "x"

    _, outside_error, outside_status = resolve_home_path(
        "/etc/passwd", root=tmp_path, home=tmp_path)
    assert outside_status == 403
    assert outside_error == "path outside home directory"

    _, traversal_error, traversal_status = resolve_home_path(
        "../x", root=tmp_path, home=tmp_path)
    assert traversal_status == 400
    assert traversal_error == "path traversal not allowed"
