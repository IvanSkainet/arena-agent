"""v4.169.24 -- the update endpoint's own guards were never tested.

A mutation sweep over `arena/admin/handlers_update.py` killed 5 mutants
and let **213** survive. Most of those are noise -- renaming a key in a
response body that nothing asserts on -- but two were not:

    mutant 90:  - if not expected and not accept_no_verification:
                + if     expected and not accept_no_verification:

    mutant 180: - force = bool(... body.get("force", False))
                + force = bool(... body.get("force", True))

The first inverts the digest requirement: an update with **no**
`expected_sha256` sails through, and one that supplies a digest is
rejected instead. That endpoint unpacks an archive over the bridge's own
code. The second makes `force` the default, so a restart on a host with
no way to relaunch stops the bridge instead of refusing -- exactly the
failure v4.169.21 was written to prevent.

Both survived because nothing called the handler. `test_auto_update_digest_required`
covers `download_release`, one layer below; `test_handlers_update_v4_60_13`
read the source as text. The HTTP layer where the decision actually
happens had no test at all, so the guards could be inverted and the
suite stayed green.

These call the real coroutine through `make_mocked_request` and assert on
the response, which is the only thing that cannot be satisfied by an
inverted condition.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from arena.admin.handlers_update import make_update_handlers


class _Ctx:
    """The four methods handlers_update actually uses."""

    def __init__(self) -> None:
        self.audits: list[dict[str, Any]] = []
        self.executor = None

    def require_auth(self, _request):
        return None

    def record_request(self, *_a, **_kw):
        return None

    def audit(self, event):
        self.audits.append(event)

    def cors_json_response(self, payload, status: int = 200):
        return web.json_response(payload, status=status)


def _post(handler, body: dict[str, Any]):
    """Drive a handler with a JSON body and return (status, parsed)."""
    payload = json.dumps(body).encode()
    request = make_mocked_request(
        "POST", "/v1/admin/update/apply",
        headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
        payload=None,
    )

    async def _json():
        return json.loads(payload)

    request.json = _json  # type: ignore[method-assign]
    response = asyncio.run(handler(request))
    return response.status, json.loads(response.text)


def _handlers():
    return make_update_handlers(_Ctx())


# --- mutant 90: the digest requirement --------------------------------------

def test_apply_without_a_digest_is_refused() -> None:
    """No `expected_sha256` and no explicit waiver means no install.

    Inverting this condition -- the mutant that survived -- makes an
    unverified archive the accepted case.
    """
    status, body = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9",
        "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip",
    })
    assert status == 400, body
    assert body["ok"] is False
    assert "expected_sha256" in body["error"]


def test_apply_with_a_digest_is_not_refused_for_lacking_one() -> None:
    """The mirror image, which is what actually kills the mutant.

    An inverted condition rejects exactly the requests a correct one
    accepts, so testing only the refusal above would still pass on the
    mutated code.
    """
    status, body = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9",
        "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip",
        "expected_sha256": "a" * 64,
    })
    # It stops at the consent step, not at the digest check. Whatever
    # else happens, the complaint must not be about a missing digest.
    assert "expected_sha256 required" not in json.dumps(body)


def test_missing_required_fields_are_refused_before_anything_else() -> None:
    status, body = _post(_handlers()["update_apply"], {"tag": "v9.9.9"})
    assert status == 400
    assert "required" in body["error"]


def test_consent_is_required_even_with_a_valid_digest() -> None:
    """A digest proves what will be installed, not that anyone asked."""
    _status, body = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9",
        "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip",
        "expected_sha256": "b" * 64,
    })
    assert body.get("consent_required") is True
    assert body.get("required_consent")


def test_unverified_path_has_its_own_consent_token() -> None:
    """A consent minted for a verified install must not unlock an
    unverified one -- otherwise a stored token is a replay tool."""
    verified = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": "c" * 64,
    })[1].get("required_consent")
    unverified = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "accept_no_verification": True,
    })[1].get("required_consent")

    assert verified and unverified
    assert verified != unverified, (
        "the two paths share a consent token, so one can be replayed "
        "to trigger the other"
    )


# --- mutant 180: force must be opt-in ---------------------------------------

def test_restart_does_not_force_by_default(monkeypatch) -> None:
    """`force=True` by default turns a refusal into a shutdown.

    v4.169.21 made `restart_process` refuse when nothing can relaunch
    the bridge. Defaulting `force` to True walks straight past that and
    stops the bridge on a host that cannot come back -- which is how the
    PC stayed down three times.
    """
    from arena.admin import handlers_update as hu

    seen: dict[str, Any] = {}

    def fake_restart(*, force: bool = False, **_kw):
        seen["force"] = force
        return {"ok": True, "restart": "scheduled"}

    monkeypatch.setattr(hu._upd, "restart_process", fake_restart)

    handlers = make_update_handlers(_Ctx())
    request = make_mocked_request(
        "POST", "/v1/admin/update/restart",
        headers={"Authorization": "Bearer t"})

    async def _json():
        return {}

    request.json = _json  # type: ignore[method-assign]
    asyncio.run(handlers["update_restart"](request))

    assert seen["force"] is False, (
        "force must be opt-in: defaulting it to True stops a bridge that "
        "has no way to restart"
    )


def test_restart_forces_when_explicitly_asked(monkeypatch) -> None:
    """Reverse check: the operator can still insist."""
    from arena.admin import handlers_update as hu

    seen: dict[str, Any] = {}

    def fake_restart(*, force: bool = False, **_kw):
        seen["force"] = force
        return {"ok": True, "restart": "scheduled", "forced": force}

    monkeypatch.setattr(hu._upd, "restart_process", fake_restart)

    handlers = make_update_handlers(_Ctx())
    request = make_mocked_request(
        "POST", "/v1/admin/update/restart",
        headers={"Authorization": "Bearer t"})

    async def _json():
        return {"force": True}

    request.json = _json  # type: ignore[method-assign]
    asyncio.run(handlers["update_restart"](request))

    assert seen["force"] is True


def test_restart_survives_a_body_that_is_not_json(monkeypatch) -> None:
    """The Windows installer callback posts with no body at all."""
    from arena.admin import handlers_update as hu

    monkeypatch.setattr(hu._upd, "restart_process",
                        lambda **_kw: {"ok": True, "restart": "scheduled"})

    handlers = make_update_handlers(_Ctx())
    request = make_mocked_request(
        "POST", "/v1/admin/update/restart",
        headers={"Authorization": "Bearer t"})

    async def _boom():
        raise ValueError("not json")

    request.json = _boom  # type: ignore[method-assign]
    response = asyncio.run(handlers["update_restart"](request))
    assert response.status == 200


# --- the sweep was overstating the gap --------------------------------------

def test_sweep_includes_cross_cutting_guards() -> None:
    """A sweep that omits suite-wide guards invents survivors.

    Removing `@authed(ctx)` from a handler is reported as a survivor by
    a run whose test list is just the per-file tests -- yet
    `test_auth_surface_guard.py` fails on that mutation immediately. The
    map was sending me to write tests that already existed, which is a
    worse failure than a missing test: it wastes the effort *and* makes
    the real gaps harder to see.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
    import mutation_sweep

    names = [guard for guard, _markers in mutation_sweep.CROSS_CUTTING_GUARDS]
    assert "tests/test_auth_surface_guard.py" in names

    # It reaches a curated target that serves HTTP...
    assert mutation_sweep._guards_for("arena/admin/handlers_update.py",
                                      curated=True)
    # ...and not a curated target with no handlers in it.
    assert not mutation_sweep._guards_for("arena/files/sandbox.py", curated=True)
    # And never during a whole-tree sweep. Two measurements got here:
    # adding it everywhere took a shard from 76s to a hard timeout, and
    # narrowing to "filename says handlers" still caught 18 files in one
    # shard -- also a timeout. The whole-tree run exists to find weak
    # spots cheaply; finishing beats precision there.
    assert not mutation_sweep._guards_for("arena/admin/handlers_update.py")

    source = __import__("inspect").getsource(mutation_sweep._run_one)
    assert "_guards_for" in source, (
        "the guards are declared but never added to the runner"
    )


def test_handlers_update_is_a_mutation_target() -> None:
    """It carries the auto-update entry point; it belongs in the sweep."""
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
    from mutation_gate import TARGETS

    assert "arena/admin/handlers_update.py" in TARGETS
    tests = TARGETS["arena/admin/handlers_update.py"]
    assert "tests/test_update_apply_guards_v4_169_24.py" in tests


# --- the digest must reach apply_update, not just the consent prompt --------

def test_the_digest_is_passed_through_to_apply_update(monkeypatch) -> None:
    """`expected or None` -> `expected and None` disables verification.

    That mutation survived the first sweep. It is the worst one in the
    file: `x and None` is always None, so `apply_update` is called with
    no digest at all -- while the consent prompt the operator approved
    still displayed the real SHA. The install would proceed unverified
    and every log line would say it was checked.
    """
    from arena.admin import handlers_update as hu

    seen: dict[str, Any] = {}

    def fake_apply(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "verification": "sha256", "applied_version": "9.9.9"}

    monkeypatch.setattr(hu._upd, "apply_update", fake_apply)

    digest = "d" * 64
    handlers = make_update_handlers(_Ctx())
    consent = _post(handlers["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": digest,
    })[1]["required_consent"]

    _post(handlers["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": digest,
        "consent": consent, "restart": False,
    })

    assert seen.get("expected_sha256") == digest, (
        f"apply_update was called with expected_sha256={seen.get('expected_sha256')!r} "
        f"-- an unverified install behind a verified-looking consent"
    )


def test_consent_prompt_reports_the_digest_it_will_use() -> None:
    """`sha256: expected and None` blanks the field the operator reads."""
    digest = "e" * 64
    _status, body = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": digest,
    })
    assert body["sha256"] == digest
    assert body["verification"] == "sha256"


def test_consent_prompt_says_unverified_when_it_is() -> None:
    """The mirror case: inverting the conditional swaps the two labels,
    so a verified install would be announced as unverified and vice
    versa. Checking only one side leaves that mutation alive."""
    _status, body = _post(_handlers()["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "accept_no_verification": True,
    })
    assert body["verification"] == "unverified"
    assert body["sha256"] is None


def test_every_required_field_is_required_on_its_own() -> None:
    """`tag and url and name` -> `tag or url and name` still passes with
    only a tag. Each field has to be tested alone, or the mutation that
    loosens one of them survives."""
    base = {"tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
            "asset_name": "a.zip"}
    for missing in base:
        body = {k: v for k, v in base.items() if k != missing}
        body["expected_sha256"] = "f" * 64
        status, parsed = _post(_handlers()["update_apply"], body)
        assert status == 400, f"omitting {missing} was accepted: {parsed}"
        assert "required" in parsed["error"]


def test_restart_defaults_to_true_for_the_apply_endpoint(monkeypatch) -> None:
    """`restart` defaults True here (unlike `force`): the dashboard
    Install button relies on it, and flipping the default silently turns
    every install into one that needs a manual restart."""
    from arena.admin import handlers_update as hu

    seen: dict[str, Any] = {}
    monkeypatch.setattr(hu._upd, "apply_update",
                        lambda **kw: (seen.update(kw), {"ok": True})[1])
    monkeypatch.setattr(hu._upd, "restart_process",
                        lambda **_kw: {"ok": True, "restart": "scheduled"})

    digest = "a" * 64
    handlers = make_update_handlers(_Ctx())
    consent = _post(handlers["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": digest,
    })[1]["required_consent"]

    _post(handlers["update_apply"], {
        "tag": "v9.9.9", "asset_url": "https://example.invalid/a.zip",
        "asset_name": "a.zip", "expected_sha256": digest, "consent": consent,
    })
    assert seen.get("restart") is True


def test_sweep_stashes_the_original_before_mutating() -> None:
    """`finally` does not run when the process is killed outright.

    mutmut 2.5.1 mutates in place. The sweep already restores the file
    in a `finally`, which covers a timeout or an exception -- but not
    SIGKILL from a job runner or an outer `timeout` command. That
    happened twice while wiring this file into TARGETS: an interrupted
    run left `"source"` rewritten to `"XXsourceXX"` in the working tree,
    and the next sweep then cached its result against the *mutated*
    file's hash, so the cache silently stopped matching and every run
    recomputed from scratch.

    A sidecar copy makes the damage recoverable without git, which
    matters when the sweep runs where the checkout is not clean.
    """
    import inspect
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
    import mutation_sweep

    source = inspect.getsource(mutation_sweep._run_one)
    assert ".mutation-sweep-original" in source
    # Written before the subprocess starts, or it protects nothing.
    assert source.index("stash.write_bytes") < source.index("subprocess.run")
    assert "stash.unlink" in source


def test_the_stash_file_is_gitignored() -> None:
    """A sidecar that gets committed is worse than no sidecar."""
    from pathlib import Path as _Path

    ignored = (_Path(__file__).resolve().parents[1] / ".gitignore").read_text(
        encoding="utf-8")
    assert ".mutation-sweep-original" in ignored
