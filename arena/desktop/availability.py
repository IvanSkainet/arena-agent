"""Telling "this box cannot" apart from "this bridge broke" (#260).

`POST /v1/desktop/click_text` on a machine without tesseract answered
`500 {"error": "tesseract is not installed"}`. Everything about that is
wrong except the sentence: 5xx means the server failed, so a caller retries,
and a retry cannot install tesseract. Schemathesis reports it as a server
error, which is also correct -- it is the last unique 500 left after #259.

503 is the honest answer. The operation is implemented, the request is
valid, and the same request returns 200 once the tool is there. `Retry-After`
is deliberately absent: nobody can say when a human will run `apt install`.

Not 501: 501 says the *bridge* does not implement the method, which would be
a lie about the code rather than about the machine, and would make a caller
give up on an endpoint that works everywhere else.

The body keeps the message it always had and adds one machine-readable
field:

    503 {"ok": false,
         "error": "tesseract is not installed",
         "unavailable": ["tesseract"]}

`unavailable` lists what to install, in the order the code prefers them --
any one of them is enough. A client that cannot read English still knows
what is missing, and the contract test can tell an unavailability apart from
a genuine failure without matching on prose.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The response field naming the tools that would make the call work.
UNAVAILABLE = "unavailable"

__all__ = [
    "UNAVAILABLE",
    "MissingTool",
    "builder_refusal",
    "failure_response",
    "failure_status",
    "unavailable_result",
]


class MissingTool(str):
    """An error message that also knows which tools would fix it.

    A `str` subclass rather than a new type, because every producer of these
    messages already returns a plain string and every consumer already
    compares, logs and formats one. Existing call sites keep working
    untouched; only the handlers that want to answer 503 have to look at
    `needs`, and `isinstance` is what tells them they may.
    """

    needs: tuple[str, ...]

    def __new__(cls, message: str, needs: tuple[str, ...]) -> MissingTool:
        self = super().__new__(cls, message)
        self.needs = needs
        return self


def unavailable_result(error: MissingTool) -> dict[str, Any]:
    """The 503 body: the message that was always there, plus the tool list."""
    return {"ok": False, "error": str(error), UNAVAILABLE: list(error.needs)}


def builder_refusal(error: str) -> tuple[dict[str, Any], int]:
    """The body and status for an error a `build_*_command` handed back.

    Two kinds arrive here and they are not the same thing:

    * :class:`MissingTool` -- no ydotool, no xdotool, nothing. The box cannot
      do this at all, so 503 and the list of tools.
    * anything else -- currently only `build_key_command`'s "unknown key
      'foo'", which is the caller naming a key that does not exist. That is a
      400, and it used to be a 500: the same defect as #254 in different
      clothes. The Windows branch of the same handler already answered 400,
      so this is the two paths agreeing rather than a new opinion.
    """
    if isinstance(error, MissingTool):
        return unavailable_result(error), 503
    return {"ok": False, "error": str(error)}, 400


def failure_status(result: Mapping[str, Any]) -> int:
    """503 when a result carries a non-empty `unavailable`, else 500.

    For the handlers that pass a whole result dict through rather than an
    error string. The emptiness check matters: a producer that sets the key
    to `[]` is saying "nothing is missing", which is a real failure and has
    to stay a 500 rather than becoming a 503 that promises a fix nobody can
    perform.
    """
    return 503 if result.get(UNAVAILABLE) else 500


def failure_response(ctx, result: dict[str, Any], fallback: str = "operation failed"):
    """The response for a producer's failed result, whatever kind of failure it is.

    Three handlers had the same four lines -- pick a status, decide whether
    it counts as an error, keep the message -- and three copies of a rule
    are three chances to fix it in two places. It lives here because the
    rule *is* the contract: a missing tool never counts, everything else
    always does.

    A result may also carry its own `status` (the text-target handler's 404
    for "nothing matched"); that wins over the 500 default and still counts.
    """
    status = 503 if result.get(UNAVAILABLE) else int(result.pop("status", 500) or 500)
    result.pop("status", None)
    if status != 503:
        # A missing tool is not this bridge failing. Counting it would make
        # a headless box -- behaving exactly as configured -- report itself
        # unhealthy the moment a client asks it for a screenshot (#260).
        ctx.record_request(is_error=True, count_request=False)
    body = dict(result)
    body["ok"] = False
    body["error"] = str(body.get("error") or fallback)
    return ctx.cors_json_response(body, status=status)
