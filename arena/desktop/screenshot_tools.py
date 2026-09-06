"""Which screenshot tool this host could use, and what to say when none.

Split out of screenshot.py: that module is already one of the more complex
in the tree, and the answer to "who could take this picture" is a table and
two small functions with no I/O in them, testable on its own (#260).
"""
from typing import Any

from arena.desktop.availability import MissingTool

# grim only works under Wayland and scrot only under X11 -- the branches in
# the capture check that as well as the binary. Telling an X11 user to install
# grim would have them install it and keep getting 503s, so the list is
# filtered by the session whenever the session is known. When it is neither --
# a headless container, where all three are equally absent and equally
# hypothetical -- the full list is the honest answer.
SCREENSHOT_TOOLS: tuple[tuple[str, str | None], ...] = (
    ("spectacle", None), ("grim", "wayland"), ("scrot", "x11"))


def screenshot_message(needs: tuple[str, ...]) -> str:
    """"...(need spectacle, grim, or scrot)", or what is left after filtering.

    The sentence has to agree with the list beside it: having dropped grim on
    X11, telling the reader they need grim contradicts the `unavailable` field
    in the same response and sends them to install the one tool that cannot
    work here.
    """
    listed = ", ".join(needs[:-1]) + ", or " + needs[-1] if len(needs) > 2 else " or ".join(needs)
    return f"No screenshot tool available (need {listed})"


def missing_screenshot_tool(env: dict[str, Any]) -> MissingTool:
    """The refusal, naming only the tools that could actually run here."""
    session = env.get("wayland") or env.get("x11")
    needs = tuple(
        tool for tool, requires in SCREENSHOT_TOOLS
        if not session or requires is None or env.get(requires))
    return MissingTool(screenshot_message(needs), needs)
