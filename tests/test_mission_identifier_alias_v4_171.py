"""Mission GET endpoints must accept the identifier they advertise (#130).

Reproduced on the live bridge (v4.169.48) before the fix:

    GET /v1/mission/status?name=scenario-armed-posture-live-proof-41470       -> 200
    GET /v1/mission/status?mission_id=scenario-armed-posture-live-proof-41470 -> 400
        {"error": "missing required parameter 'name' (or 'mission_id')"}
    GET /v1/mission/status?name=armed-posture-live-proof-41470                -> 404

Same on report/history/lineage/family/show. Two defects, both live:

1. The 400 body offers `mission_id` and every handler reads `name` only,
   so a client that follows the hint it was just handed gets the same
   400 again -- forever. The MCP tools accept both keys and normalise
   them (`arena/mcp/tool_mission.py`), so REST and MCP disagreed about
   the API they jointly expose.
2. `scenario.list` reports a short `name` (`armed-posture-...`) and a
   prefixed `mission_id` (`scenario-armed-posture-...`). Only the
   prefixed spelling exists on disk, so the field called `name` 404s
   against the parameter called `name`.

The tests below pin both, plus the boundaries that make the fix safe to
ship: traversal still rejected, unknown missions still 404 under the
name the caller used, and an existing mission never silently rewritten.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.resources.mission_catalog import mission_dir  # noqa: E402
from arena.resources.mission_identifier import (  # noqa: E402
    IDENTIFIER_KEYS,
    SCENARIO_PREFIX,
    parse_mission_identifier,
    resolve_mission_name,
)
from arena.resources.mission_state import get_mission_status  # noqa: E402


@pytest.fixture
def missions(tmp_path: Path) -> Path:
    """A store holding a scenario mission and a plain one."""
    (tmp_path / "scenario-armed-posture-live-proof-41470").mkdir()
    (tmp_path / "plain-mission").mkdir()
    return tmp_path


# --- defect 1: the advertised alias must actually work -----------------------

@pytest.mark.parametrize("query,expected", [
    ("name=abc", "abc"),
    ("mission_id=abc", "abc"),
    # Both supplied and equal: unambiguous.
    ("name=abc&mission_id=abc", "abc"),
    # `name` wins when they disagree -- it is the spelling the endpoint
    # documents in its own hint.
    ("mission_id=abc&name=xyz", "xyz"),
    # A blank `name` must not mask a usable `mission_id`.
    ("name=&mission_id=abc", "abc"),
    ("mission_id=&name=abc", "abc"),
])
def test_both_advertised_spellings_are_accepted(query, expected):
    assert parse_mission_identifier(query) == expected


@pytest.mark.parametrize("query", ["", "foo=1", "name=", "mission_id=", "name=&mission_id="])
def test_a_missing_identifier_is_reported_as_missing(query):
    """Empty means empty -- callers turn this into the 400 naming both keys."""
    assert parse_mission_identifier(query) == ""


def test_the_error_message_and_the_parser_agree_on_the_accepted_keys():
    """The 400 advertises exactly the keys the parser accepts.

    This is the actual bug class: the message and the code drifted, and
    nothing failed. If someone adds a third alias to the hint text
    without teaching the parser, this fails.
    """
    handlers = (Path(__file__).resolve().parents[1] / "arena" / "resources" / "handlers.py").read_text(
        encoding="utf-8"
    )
    assert "missing required parameter 'name' (or 'mission_id')" in handlers
    assert IDENTIFIER_KEYS == ("name", "mission_id")


# --- defect 2: the short scenario name must resolve --------------------------

def test_a_short_scenario_name_resolves_to_the_stored_mission(missions):
    """`scenario.list` hands out this spelling; it must be usable."""
    assert resolve_mission_name(missions, "armed-posture-live-proof-41470") == (
        "scenario-armed-posture-live-proof-41470"
    )


def test_the_full_scenario_id_still_resolves_to_itself(missions):
    full = "scenario-armed-posture-live-proof-41470"
    assert resolve_mission_name(missions, full) == full


def test_an_existing_plain_mission_is_never_rewritten(missions):
    """Only a *missing* identifier is retried with the prefix."""
    assert resolve_mission_name(missions, "plain-mission") == "plain-mission"


def test_an_unknown_mission_keeps_the_name_the_caller_used(missions):
    """A 404 must name what was asked for, not a rewritten guess."""
    assert resolve_mission_name(missions, "no-such-mission") == "no-such-mission"
    result = get_mission_status(missions, "no-such-mission")
    assert result["status"] == 404
    assert "no-such-mission" in result["error"]
    assert SCENARIO_PREFIX + "no-such-mission" not in result["error"]


def test_a_prefixed_name_is_not_prefixed_twice(missions):
    """`scenario-scenario-...` would be a silent double-prefix bug."""
    assert resolve_mission_name(missions, "scenario-nope") == "scenario-nope"


def test_status_reads_a_mission_through_the_short_name(missions):
    """End-to-end through the real lookup, not just the resolver."""
    (missions / "scenario-armed-posture-live-proof-41470" / "mission.json").write_text(
        '{"title": "Armed posture live proof"}', encoding="utf-8"
    )
    result = get_mission_status(missions, "armed-posture-live-proof-41470")
    assert result["ok"] is True


# --- boundaries: the resolver stats paths, so it must not be the weak link ---

@pytest.mark.parametrize("bad", [
    "../etc", "..", "a/b", "a\\b", ".hidden", "../../scenario-armed-posture-live-proof-41470",
])
def test_traversal_is_still_rejected_before_any_filesystem_probe(missions, bad):
    with pytest.raises(ValueError):
        mission_dir(missions, bad)


@pytest.mark.parametrize("bad", ["../etc", "..", "a/b", "a\\b", ".hidden"])
def test_the_resolver_itself_never_rewrites_an_unsafe_name(missions, bad):
    """Defence in depth: `mission_dir` validates, but this runs first."""
    assert resolve_mission_name(missions, bad) == bad


def test_an_empty_identifier_resolves_to_empty(missions):
    assert resolve_mission_name(missions, "") == ""


def test_resolution_survives_an_unreadable_store(tmp_path, monkeypatch):
    """A stat failure must not turn a lookup into a 500."""
    def boom(self):  # noqa: ANN001
        raise OSError("mount vanished")

    monkeypatch.setattr(Path, "exists", boom)
    assert resolve_mission_name(tmp_path, "some-mission") == "some-mission"


def test_mission_dir_resolves_the_short_name_for_every_reader(missions):
    """Every mission read funnels through `mission_dir`, so fix it once."""
    resolved = mission_dir(missions, "armed-posture-live-proof-41470")
    assert resolved.name == "scenario-armed-posture-live-proof-41470"
    assert resolved.exists()


# --- through the real handlers: parsing is wired, not just correct -----------
#
# The resolver being right is not the fix; the fix is every mission GET
# endpoint calling it. These drive the actual aiohttp handlers, because
# a per-handler `parse_qs(...)["name"]` left behind would pass every
# test above and still 400 in production -- which is precisely how #130
# happened.

def _resource_handlers(seen):
    import unified_bridge as ub
    from arena.handler_context import ResourceHandlerContext
    from arena.resources.handlers import make_resource_handlers

    def record(name):
        def _sync(value):
            seen.append((name, value))
            return {"ok": True, "asked": value}
        return _sync

    return make_resource_handlers(ResourceHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *a, **k: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        # Return types match the declared protocol in
        # arena/contexts/domain.py: the two list_* helpers are
        # Callable[[], list[dict]], the three *_list_sync ones are
        # Callable[[], dict].
        list_missions_sync=lambda: [],
        list_reports_sync=lambda: [],
        hooks_list_sync=lambda: {"ok": True, "hooks": []},
        agents_list_sync=lambda: {"ok": True, "agents": []},
        subagents_list_sync=lambda: {"ok": True, "subagents": []},
        mission_show_sync=record("show"),
        mission_status_sync=record("status"),
        mission_report_sync=record("report"),
        mission_history_sync=record("history"),
        mission_lineage_sync=record("lineage"),
        mission_catalog_sync=lambda payload: {"ok": True},
        mission_templates_sync=lambda: {"ok": True},
        mission_compose_sync=lambda data: {"ok": True},
        mission_propose_sync=lambda data: {"ok": True},
        mission_create_sync=lambda data: {"ok": True},
        mission_run_sync=lambda data: {"ok": True},
        mission_rerun_sync=lambda data: {"ok": True},
        mission_recover_sync=lambda data: {"ok": True},
        mission_followup_sync=lambda data: {"ok": True},
        mission_iterate_sync=lambda data: {"ok": True},
        subagent_spawn_sync=lambda data: {"ok": True},
        audit=lambda event: None,
    ))


class _Request:
    """Minimal stand-in: the handlers only read query_string and path."""

    def __init__(self, query_string: str, path: str = "/v1/mission/status") -> None:
        self.query_string = query_string
        self.path = path
        self.method = "GET"
        self.headers: dict[str, str] = {}

    def __getitem__(self, key):
        raise KeyError(key)

    def __setitem__(self, key, value):
        pass


@pytest.mark.parametrize("endpoint", ["status", "report", "history", "lineage", "show"])
@pytest.mark.parametrize("spelling", ["name", "mission_id"])
def test_every_mission_get_endpoint_accepts_both_spellings(endpoint, spelling):
    import asyncio

    seen: list[tuple[str, str]] = []
    handlers = _resource_handlers(seen)
    handler = getattr(handlers, f"mission_{endpoint}")

    response = asyncio.run(handler(_Request(f"{spelling}=demo-mission")))

    assert response.status == 200, (
        f"/v1/mission/{endpoint} rejected ?{spelling}= -- the 400 body "
        "advertises both spellings"
    )
    assert seen == [(endpoint, "demo-mission")]


@pytest.mark.parametrize("endpoint", ["status", "report", "history", "lineage", "show"])
def test_a_mission_get_with_no_identifier_still_400s(endpoint):
    """The reverse: dropping the requirement entirely is not the fix."""
    import asyncio

    seen: list[tuple[str, str]] = []
    handlers = _resource_handlers(seen)
    handler = getattr(handlers, f"mission_{endpoint}")

    response = asyncio.run(handler(_Request("")))

    assert response.status == 400
    assert seen == [], "handler reached the store without an identifier"


@pytest.mark.parametrize("spelling", ["name", "mission_id"])
def test_mission_family_accepts_both_spellings(spelling):
    """`family` lives in a different module and drifted independently."""
    import asyncio

    import unified_bridge as ub
    from arena.handler_context import MissionLifecycleHandlerContext
    from arena.resources.mission_lifecycle_handlers import (
        make_mission_lifecycle_handlers,
    )

    seen: list[str] = []

    ctx_kwargs = dict(
        require_auth=lambda request: None,
        record_request=lambda *a, **k: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        mission_family_sync=lambda value: (seen.append(value) or {"ok": True}),
    )
    for field in fields(MissionLifecycleHandlerContext):
        ctx_kwargs.setdefault(field.name, lambda *a, **k: {"ok": True})

    handlers = make_mission_lifecycle_handlers(
        MissionLifecycleHandlerContext(**ctx_kwargs)
    )
    response = asyncio.run(
        handlers.mission_family(_Request(f"{spelling}=demo-mission", "/v1/mission/family"))
    )

    assert response.status == 200
    assert seen == ["demo-mission"]


# --- cases the first round of sabotage walked straight through ---------------
#
# S4/S5/S7 below survived the initial test set: the fixtures were not
# sharp enough to tell a correct resolver from a sloppy one. Each test
# here exists because a specific mutation of the resolver passed.

def test_an_exact_match_wins_over_a_prefixed_one(tmp_path):
    """Ambiguity resolves to what the caller literally named.

    With both `plain-mission` and `scenario-plain-mission` present, a
    resolver that tries the prefix first silently reads the wrong
    mission -- and reports success, which is worse than a 404.
    """
    (tmp_path / "plain-mission").mkdir()
    (tmp_path / "scenario-plain-mission").mkdir()
    assert resolve_mission_name(tmp_path, "plain-mission") == "plain-mission"


def test_an_already_prefixed_name_is_never_prefixed_again(tmp_path):
    """`scenario-weird` must not silently become `scenario-scenario-weird`."""
    (tmp_path / "scenario-scenario-weird").mkdir()
    assert resolve_mission_name(tmp_path, "scenario-weird") == "scenario-weird"


@pytest.mark.parametrize("bad", [
    "../etc", "..", "a/b", "a\\b", ".hidden",
    # A `..` with no separator and no leading dot: caught by none of the
    # other clauses, so without this case the `".." in name` check can be
    # deleted and every test still passes (mutation-verified).
    "mission..name", "run..",
])
def test_an_unsafe_name_is_never_probed_on_the_filesystem(tmp_path, monkeypatch, bad):
    """The guard must short-circuit *before* any stat.

    `mission_dir` rejects traversal, but this resolver runs first and
    touches the filesystem. Asserting only on the return value cannot
    tell "refused" from "probed and found nothing" -- so spy on the
    probe itself.
    """
    probed: list[str] = []
    real_exists = Path.exists

    def spy(self, *args, **kwargs):  # noqa: ANN001
        probed.append(str(self))
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", spy)
    assert resolve_mission_name(tmp_path, bad) == bad
    assert probed == [], f"unsafe name reached the filesystem: {probed}"


def test_a_safe_name_is_still_probed(tmp_path):
    """Reverse of the above: the guard must not disable resolution."""
    (tmp_path / "scenario-real-run").mkdir()
    assert resolve_mission_name(tmp_path, "real-run") == "scenario-real-run"


# --- the spec must describe what the code actually accepts -------------------

def test_the_openapi_spec_documents_both_identifier_parameters():
    """A spec that omits `mission_id` recreates the original confusion.

    #130 was, at root, three surfaces disagreeing about one parameter.
    Fixing the handlers without fixing the published spec leaves a
    fourth disagreement in place.
    """
    from types import SimpleNamespace

    from arena.public.openapi import build_openapi_spec

    spec = build_openapi_spec(SimpleNamespace(
        version="test-version",
        hostname=lambda: "localhost",
        bridge_port=lambda: 8765,
    ))
    documented = [
        "/v1/mission/status", "/v1/mission/report",
        "/v1/mission/history", "/v1/mission/lineage", "/v1/mission/family",
    ]
    for path in documented:
        params = {p["name"] for p in spec["paths"][path]["get"]["parameters"]}
        assert params == {"name", "mission_id"}, f"{path} documents {params}"
        # Neither may be flagged required on its own: either one suffices.
        for param in spec["paths"][path]["get"]["parameters"]:
            assert param["required"] is False, f"{path}:{param['name']}"


# --- show_mission: the reader that does not go through mission_dir -----------
#
# Caught in review on this PR, and a fair hit: the claim was "fix it in
# one place because every reader funnels through `mission_dir`", but
# `show_mission` predates that helper and does its own lookup. So
# /v1/mission/show 404'd on the short scenario name while
# /v1/mission/status answered 200 for the identical identifier -- the
# exact inconsistency #130 is about, surviving inside its own fix.
#
# The handler-level test above only exercised the `mission_id` alias for
# `show`, which is why it passed. These use the short name.

def test_show_resolves_the_short_scenario_name(tmp_path):
    from arena.resources.listing import show_mission

    mission = tmp_path / "scenario-my-run"
    mission.mkdir()
    (mission / "mission.json").write_text('{"title": "t"}', encoding="utf-8")

    assert show_mission(tmp_path, "my-run")["ok"] is True


def test_show_and_status_agree_on_every_spelling(tmp_path):
    """The two readers must never disagree about the same identifier."""
    from arena.resources.listing import show_mission

    mission = tmp_path / "scenario-my-run"
    mission.mkdir()
    (mission / "mission.json").write_text('{"title": "t"}', encoding="utf-8")

    for spelling in ("my-run", "scenario-my-run"):
        assert show_mission(tmp_path, spelling).get("ok") is True, spelling
        assert get_mission_status(tmp_path, spelling).get("ok") is True, spelling


def test_show_still_refuses_traversal(tmp_path):
    """Resolution must not weaken the guard that runs before it."""
    from arena.resources.listing import show_mission

    for bad in ("../etc", "..", "a/b", "a\\b", ".hidden"):
        assert show_mission(tmp_path, bad)["error"] == "invalid mission name", bad


def test_show_reports_the_name_the_caller_used_when_missing(tmp_path):
    from arena.resources.listing import show_mission

    assert "no-such" in show_mission(tmp_path, "no-such")["error"]


# --- the machine-readable contract must match the prose ----------------------
#
# Review catch: the 400 body's `required` field still said `["name"]`
# after the handlers began accepting `mission_id`. That is #130 one
# layer down -- a client that parses the structured field instead of the
# English sentence gets the same wrong answer the sentence used to give.

@pytest.mark.parametrize("endpoint", ["status", "report", "history", "lineage", "show"])
def test_the_400_body_lists_every_key_the_handler_accepts(endpoint):
    import asyncio
    import json

    handlers = _resource_handlers([])
    response = asyncio.run(getattr(handlers, f"mission_{endpoint}")(_Request("")))
    payload = json.loads(response.body.decode())

    assert payload["accepts"] == list(IDENTIFIER_KEYS)
    assert payload["required"] == ["name|mission_id"], (
        "the structured contract still claims only one key is accepted"
    )
    for key in IDENTIFIER_KEYS:
        assert key in payload["error"], f"{key} missing from the prose error"


def test_mission_family_400_body_matches_too():
    """`family` has its own copy of the payload and drifted before."""
    import asyncio
    import json

    import unified_bridge as ub
    from arena.handler_context import MissionLifecycleHandlerContext
    from arena.resources.mission_lifecycle_handlers import (
        make_mission_lifecycle_handlers,
    )

    ctx_kwargs = dict(
        require_auth=lambda request: None,
        record_request=lambda *a, **k: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
    )
    for field in fields(MissionLifecycleHandlerContext):
        ctx_kwargs.setdefault(field.name, lambda *a, **k: {"ok": True})

    handlers = make_mission_lifecycle_handlers(
        MissionLifecycleHandlerContext(**ctx_kwargs)
    )
    response = asyncio.run(
        handlers.mission_family(_Request("", "/v1/mission/family"))
    )
    payload = json.loads(response.body.decode())

    assert response.status == 400
    assert payload["accepts"] == list(IDENTIFIER_KEYS)
    assert payload["required"] == ["name|mission_id"]
