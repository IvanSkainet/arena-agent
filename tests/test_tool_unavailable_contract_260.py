"""A tool the machine does not have is a 503, not a 500 (#260).

`POST /v1/desktop/click_text` on a box without tesseract answered
`500 {"error": "tesseract is not installed"}`. Three things were wrong with
that and only the sentence was right:

* 5xx tells the caller the server broke, so it retries -- and no number of
  retries installs tesseract.
* It counted as an error on `/v1/status`, so a headless machine that is
  behaving exactly as configured reported itself unhealthy.
* Schemathesis flags it as a server error, and it was the last unique one
  after #259 -- the single finding standing between this repository and a
  fuzzing gate.

The answer is 503 plus a machine-readable list of what to install. These
tests pin all three parts: the producers mark it, the handlers answer it,
and the document says so for exactly the four operations that can.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.availability import (  # noqa: E402
    UNAVAILABLE,
    MissingTool,
    builder_refusal,
    failure_status,
    unavailable_result,
)
from arena.desktop.input import (  # noqa: E402
    build_click_command,
    build_key_command,
    build_mouse_command,
    build_type_command,
)
from arena.desktop.screenshot import capture_desktop_screenshot  # noqa: E402

# An environment dict with every tool absent: what a headless container, a
# fresh VM or a CI runner actually looks like.
NOTHING_INSTALLED: dict = {}

# The sandbox running these tests has no ydotool, no xdotool, no tesseract
# and no screenshot tool, which is exactly the condition under test -- these
# cases would be near-impossible to stage on a developer's desktop and cost
# nothing here. The set is every desktop endpoint that shells out to one:
# eight from the four builders and the OCR pair, plus resolve_text_target,
# which is the odd one out below.
TOOL_DEPENDENT_CALLS = [
    ("GET", "/v1/desktop/screenshot", None, ["spectacle", "grim", "scrot"]),
    ("POST", "/v1/desktop/ocr", {}, ["tesseract"]),
    ("POST", "/v1/desktop/find_text", {"query": "x"}, ["tesseract"]),
    ("POST", "/v1/desktop/click_text", {"query": "x"}, ["tesseract"]),
    ("POST", "/v1/desktop/resolve_text_target", {"query": "x"}, ["tesseract"]),
    ("POST", "/v1/desktop/click", {"x": 1, "y": 2}, ["ydotool", "xdotool"]),
    ("POST", "/v1/desktop/type", {"text": "a"}, ["ydotool", "wtype", "xdotool"]),
    ("POST", "/v1/desktop/key", {"key": "a"}, ["ydotool", "xdotool"]),
    ("POST", "/v1/desktop/mouse", {"x": 1, "y": 1}, ["ydotool", "xdotool"]),
]

TOKEN = "unavailable-contract-260"

# Five of the nine have a second implementation that needs nothing installed.
# On Windows, click/type/key/mouse go through user32 and the screenshot comes
# from the GDI path, so the request succeeds and there is no unavailability to
# test -- the CI runners proved it by answering 200 with `"tool": "user32"`.
# Skipped rather than deleted: the endpoints still answer 503 everywhere else,
# and the row is what the document test reads. Skipping also keeps the sweep
# from moving the mouse and typing on a Windows machine that is not a CI box.
WINDOWS_SERVES_THESE_ITSELF = frozenset({
    "/v1/desktop/screenshot",
    "/v1/desktop/click",
    "/v1/desktop/type",
    "/v1/desktop/key",
    "/v1/desktop/mouse",
})


def _needs_a_tool_here(path: str) -> bool:
    """Whether this platform reaches the missing-tool path for `path` at all."""
    return not (sys.platform == "win32" and path in WINDOWS_SERVES_THESE_ITSELF)


CALLS_FOR_THIS_PLATFORM = [
    call for call in TOOL_DEPENDENT_CALLS if _needs_a_tool_here(call[1])
]


def _spec():
    from arena.public.openapi import build_openapi_spec

    return build_openapi_spec(SimpleNamespace(
        version="test", hostname=lambda: "h", bridge_port=lambda: 8888))


# ---------------------------------------------------------------------
# 1. the producers say which tools are missing
# ---------------------------------------------------------------------
@pytest.mark.parametrize("builder,kwargs,needs", [
    (build_click_command, {"x": 1, "y": 2}, ["ydotool", "xdotool"]),
    (build_type_command, {"text": "hi"}, ["ydotool", "wtype", "xdotool"]),
    (build_mouse_command, {"x": 1, "y": 2}, ["ydotool", "xdotool"]),
])
def test_a_builder_with_no_tool_names_the_tools(builder, kwargs, needs):
    error = builder(env=NOTHING_INSTALLED, **kwargs)[2]
    assert isinstance(error, MissingTool), repr(error)
    assert list(error.needs) == needs


def test_the_key_builder_names_them_too_despite_its_extra_return_value():
    """`build_key_command` returns four values, not three."""
    error = build_key_command(env=NOTHING_INSTALLED, key="a")[2]
    assert isinstance(error, MissingTool)
    assert list(error.needs) == ["ydotool", "xdotool"]


def test_the_message_is_the_one_it_always_was():
    """A marker, not a rewrite.

    The sentence is the part a human reads and it was never the problem;
    changing it would break anyone matching on it for no gain.
    """
    error = build_click_command(env=NOTHING_INSTALLED, x=0, y=0)[2]
    assert str(error) == "No click tool available (need ydotool or xdotool)"


def test_a_missing_tool_is_still_a_string_everywhere_it_used_to_be():
    """`MissingTool` subclasses `str` so no existing call site changes.

    Producers returned a plain message and consumers formatted, logged and
    compared one. Introducing a new type would have meant touching all of
    them; this way only the handlers that answer 503 look any different.
    """
    error = build_click_command(env=NOTHING_INSTALLED, x=0, y=0)[2]
    assert isinstance(error, str)
    assert f"error: {error}".endswith("xdotool)")


def test_the_screenshot_producer_marks_it_too():
    async def never_called(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("no tool, so nothing should be executed")

    result = asyncio.run(capture_desktop_screenshot(
        fmt="png", desktop_exec=never_called,
        detect_env=lambda: NOTHING_INSTALLED))
    assert result[UNAVAILABLE] == ["spectacle", "grim", "scrot"]
    assert result["ok"] is False


# ---------------------------------------------------------------------
# 2. the status the handlers derive from that
# ---------------------------------------------------------------------
def test_a_missing_tool_from_a_builder_is_a_503_with_the_list():
    body, status = builder_refusal(
        build_click_command(env=NOTHING_INSTALLED, x=1, y=2)[2])
    assert status == 503
    assert body[UNAVAILABLE] == ["ydotool", "xdotool"]
    assert body["ok"] is False


def test_a_caller_mistake_from_a_builder_is_a_400_and_not_a_503():
    """`build_key_command` is the one builder with two kinds of error.

    "unknown key 'zzz'" is the caller naming a key that does not exist --
    nothing to install, nothing to retry. It answered 500 before #260, which
    is #254's defect in different clothes; the Windows branch of the same
    handler already answered 400, so the two paths now agree.
    """
    error = build_key_command(
        env={"has_ydotool": True}, key="zzz-not-a-key")[2]
    assert error and not isinstance(error, MissingTool), repr(error)
    body, status = builder_refusal(error)
    assert status == 400
    assert UNAVAILABLE not in body
    assert "unknown key" in body["error"]


def test_a_result_without_the_marker_stays_a_500():
    """The default has to be the pessimistic one.

    A tool that is installed and then fails -- ydotool without permission on
    /dev/uinput, tesseract on a corrupt image -- is a real failure. Calling
    that 503 would promise the caller an install that fixes nothing.
    """
    assert failure_status({"ok": False, "error": "Screenshot failed"}) == 500


def test_an_empty_marker_is_not_an_unavailability():
    """`unavailable: []` says "nothing is missing", which is a 500.

    Written as a test because the natural implementation -- `if
    UNAVAILABLE in result` -- gets this wrong, and the difference only shows
    up on a producer that builds the list conditionally.
    """
    assert failure_status({"ok": False, UNAVAILABLE: []}) == 500


def test_a_marked_result_is_a_503():
    assert failure_status({"ok": False, UNAVAILABLE: ["tesseract"]}) == 503


def test_the_body_keeps_the_sentence_and_adds_the_list():
    body = unavailable_result(MissingTool("tesseract is not installed", ("tesseract",)))
    assert body == {
        "ok": False,
        "error": "tesseract is not installed",
        "unavailable": ["tesseract"],
    }


# ---------------------------------------------------------------------
# 3. the document and the handlers agree, in both directions
# ---------------------------------------------------------------------
def test_exactly_the_tool_dependent_operations_document_503():
    """Both directions, because either one alone is a lie waiting to happen.

    Missing a 503 makes a generated client treat a documented, expected
    answer as a protocol violation; claiming one on an endpoint that cannot
    produce it sends the reader looking for a tool that is not involved.

    Compared against `TOOL_DEPENDENT_CALLS`, not against the `_NEEDS_LOCAL_TOOL`
    that produces the 503s: that comparison would be the document checked
    against itself, and would keep passing while an entry was deleted from
    both sides at once. The call table is verified against a running bridge
    by the sweep below, so this is the document checked against behaviour.
    """
    spec = _spec()
    documented = {
        (method, path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "503" in operation.get("responses", {})
    }
    # Four of the nine endpoints that answer 503 are absent from the
    # document entirely -- see the test at the end of this section.
    expected = {
        (method.lower(), path)
        for method, path, _body, _needs in TOOL_DEPENDENT_CALLS
        if path in spec["paths"]
    }
    assert documented == expected


def test_the_documented_503_names_the_tools_the_endpoint_actually_wants():
    """The prose in the document and the list on the wire are one fact.

    Again read off the live call table rather than the source dict, so that
    renaming a tool in the code without touching the document is a failure
    rather than a silent rewrite of both.
    """
    spec = _spec()
    for method, path, _body, needs in TOOL_DEPENDENT_CALLS:
        if path not in spec["paths"]:
            continue
        description = (spec["paths"][path][method.lower()]
                       ["responses"]["503"]["description"])
        for tool in needs:
            assert tool in description, f"{method} {path} does not mention {tool}"


def test_the_503_schema_requires_the_unavailable_list():
    """Required here, unlike `received` on the 400.

    This response exists only because something is missing, so the field
    that says what is missing is always there -- and a client that switches
    on it should not have to handle its absence.
    """
    spec = _spec()
    schema = (spec["paths"]["/v1/desktop/ocr"]["post"]["responses"]["503"]
              ["content"]["application/json"]["schema"])
    assert "unavailable" in schema["required"]
    assert schema["properties"]["unavailable"]["items"] == {"type": "string"}


def test_the_desktop_input_endpoints_are_not_in_the_document_at_all():
    """Why /v1/desktop/click and friends carry no 503 here.

    They answer one now, but the document does not describe them -- they are
    among the 296 registered routes the OpenAPI file leaves out (#257). This
    test exists so the next reader does not "fix" the omission by adding a
    503 to an operation that is not there, and so that whoever documents
    these endpoints properly gets a failure pointing at this list.
    """
    from arena.public.openapi import _NEEDS_LOCAL_TOOL

    spec = _spec()
    undocumented = {"/v1/desktop/click", "/v1/desktop/type",
                    "/v1/desktop/key", "/v1/desktop/mouse"}
    # They are in the behavioural table -- they do answer 503 -- and in
    # neither the document nor the list that annotates it.
    assert undocumented <= {p for _m, p, _b, _n in TOOL_DEPENDENT_CALLS}
    for path in undocumented:
        assert path not in spec["paths"]
        assert not any(p == path for _m, p in _NEEDS_LOCAL_TOOL)


# ---------------------------------------------------------------------
# 4. through the real stack, on a machine that has none of these tools
# ---------------------------------------------------------------------
async def _call(client, method, path, body):
    from tests._live_bridge import auth_header

    headers = {**auth_header(TOKEN), "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body)
    return await client.request(method, path, headers=headers, data=data)


@pytest.mark.parametrize("call", CALLS_FOR_THIS_PLATFORM,
                         ids=[f"{m} {p}" for m, p, _b, _n in CALLS_FOR_THIS_PLATFORM])
def test_every_tool_dependent_endpoint_answers_503_with_its_tool_list(tmp_path, call):
    # One `call` tuple rather than four unpacked parameters: CodeScene counts
    # arguments, and a row of the table is one thing anyway.
    method, path, body, needs = call
    from tests._live_bridge import json_payload, running_client

    async def scenario():
        async with running_client(tmp_path, TOKEN) as client:
            response = await _call(client, method, path, body)
            return response.status, await json_payload(response)

    status, payload = asyncio.run(scenario())
    assert status == 503, f"{method} {path} answered {status}: {payload}"
    assert payload["ok"] is False
    assert payload[UNAVAILABLE] == needs
    # #259's lesson: an envelope that leaks a Python class name tells the
    # caller about our internals instead of their problem.
    assert "error_type" not in payload


def test_resolve_text_target_no_longer_calls_a_missing_tool_a_success():
    """The worst of the nine: it answered 200 with `ok: false`.

    Worse than the 500s, because a client checking the status code -- which
    is what status codes are for -- read "no tesseract" as a completed
    resolution. Pinned separately from the sweep above so that a regression
    here reports itself as what it is rather than as one row of nine.
    """
    import tempfile

    from tests._live_bridge import json_payload, running_client

    async def scenario():
        with tempfile.TemporaryDirectory() as root:
            async with running_client(Path(root), TOKEN) as client:
                response = await _call(
                    client, "POST", "/v1/desktop/resolve_text_target",
                    {"query": "anything"})
                return response.status, await json_payload(response)

    status, payload = asyncio.run(scenario())
    assert status != 200
    assert status == 503
    assert payload[UNAVAILABLE] == ["tesseract"]


def test_an_unavailable_tool_does_not_make_the_bridge_look_unhealthy():
    """The counter behind `arena_bridge_errors_total` must not move.

    A headless box with no desktop tools is behaving as configured. If every
    such refusal counted as a bridge error, the operator's error rate would
    track how often clients poke endpoints this machine was never going to
    serve -- and the one number that should mean "something is wrong here"
    would mean nothing.
    """
    from arena.observability.metrics import BRIDGE_METRICS
    from tests._live_bridge import running_client

    async def scenario():
        with __import__("tempfile").TemporaryDirectory() as root:
            async with running_client(Path(root), TOKEN) as client:
                before = BRIDGE_METRICS["total_errors"]
                for method, path, body, _needs in CALLS_FOR_THIS_PLATFORM:
                    await _call(client, method, path, body)
                return before, BRIDGE_METRICS["total_errors"]

    before, after = asyncio.run(scenario())
    assert after == before, f"{after - before} refusals counted as bridge errors"


def test_a_genuine_failure_still_counts_as_one():
    """The other half of the claim above, or the first one proves nothing.

    A test that only checks "503 does not count" passes just as well against
    a bridge that stopped counting errors altogether. This sends a refusal
    that has nothing to do with any tool -- a task submission with neither a
    command nor a title -- and requires the counter to move.
    """
    from arena.observability.metrics import BRIDGE_METRICS
    from tests._live_bridge import running_client

    async def scenario():
        with __import__("tempfile").TemporaryDirectory() as root:
            async with running_client(Path(root), TOKEN) as client:
                before = BRIDGE_METRICS["total_errors"]
                response = await _call(client, "POST", "/v1/tasks", {})
                return before, BRIDGE_METRICS["total_errors"], response.status

    before, after, status = asyncio.run(scenario())
    assert status >= 400
    assert after > before, f"a real {status} failure did not count as an error"


@pytest.mark.skipif(sys.platform != "win32", reason="about the Windows branch")
@pytest.mark.parametrize("path", sorted(WINDOWS_SERVES_THESE_ITSELF))
def test_the_windows_branch_still_answers_without_any_of_these_tools(path):
    """The other side of the skip above, so it cannot hide a regression.

    Skipping five rows on Windows is only honest if something asserts *why*
    they are skipped. These endpoints have a second implementation there --
    user32 and GDI -- that no `apt install` is involved in, and a change that
    made Windows start refusing them for want of ydotool would be a real
    break that the skipped sweep would say nothing about.
    """
    from tests._live_bridge import json_payload, running_client

    method, _path, body, _needs = next(
        call for call in TOOL_DEPENDENT_CALLS if call[1] == path)

    async def scenario():
        with __import__("tempfile").TemporaryDirectory() as root:
            async with running_client(Path(root), TOKEN) as client:
                response = await _call(client, method, path, body)
                return response.status, await json_payload(response)

    status, payload = asyncio.run(scenario())
    assert status != 503, f"{method} {path} claims a missing tool: {payload}"
    assert UNAVAILABLE not in payload
