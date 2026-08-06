"""What the bridge SAYS about token rotation must match what it DOES.

Bug #66. `token_regenerate` returned this note:

    "Existing connections still use the OLD token until the bridge
     restarts. Use POST /v1/restart, or click Restart Bridge."

The opposite is true. The route assigns the new value into the live
`cfg["token"]`, and `check_auth` compares every request against exactly
that, so the previous bearer is refused from the very next request. The
e2e gate has asserted `old_status == 401` all along -- the code was right
and the sentence next to it was wrong.

The direction of the error is what makes this worth a fix rather than a
typo commit. An operator rotating a **leaked** token was told the leak
stayed live until a restart. That invites either a panicked restart of a
production bridge, or -- much worse -- the belief that an attacker still
holds a valid credential when they do not. Security advice that is wrong
in the reassuring direction is a bug; wrong in the alarming direction is
merely noise.

The Dashboard carried the same claim in its confirmation dialog, plus a
worse one: it offered "Cancel to keep current session running with old
token", and on Cancel it skipped saving the new token, leaving the page
holding a credential the bridge had already stopped accepting.
"""
from __future__ import annotations

import pathlib
import re
import tempfile

import pytest

from arena.admin.token import token_regenerate

REPO = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD_JS = REPO / "dashboard" / "assets" / "17b-settings-token-export.js"

# Phrases that assert the old credential survives the rotation. Any of
# these reappearing means the docs have drifted back out of step with the
# code.
_FALSE_PROMISES = (
    "still use the old token",
    "continue with the old token",
    "keep current session running with old token",
    "old token until the bridge restarts",
    "until the bridge restarts",
)


def _regenerate() -> dict:
    target = pathlib.Path(tempfile.mkdtemp()) / "token.txt"
    result = token_regenerate("", default_token_file=target)
    assert result["ok"] is True, result
    return result


def test_the_note_does_not_claim_the_old_token_survives():
    note = _regenerate()["note"].lower()
    for phrase in _FALSE_PROMISES:
        assert phrase not in note, (
            f"the rotation note still promises {phrase!r}; the old token is "
            f"refused from the next request onward"
        )


def test_the_note_states_the_revocation_is_immediate():
    """Silence is not good enough here.

    Removing the false sentence but saying nothing would leave an operator
    guessing about the one fact that matters when rotating a leaked
    credential.
    """
    note = _regenerate()["note"].lower()
    assert "immediat" in note, note
    assert "no restart is required" in note or "not required" in note, note


def test_the_response_carries_machine_readable_flags():
    """A script rotating tokens should not have to parse English prose."""
    result = _regenerate()
    assert result["previous_token_revoked"] is True
    assert result["restart_required"] is False


def test_a_failed_rotation_makes_no_promises_at_all():
    """Fail closed: no note, no flags, when nothing was written."""
    import os
    import stat

    if os.name == "nt":
        pytest.skip("POSIX mode bits do not deny writes on Windows")
    locked = pathlib.Path(tempfile.mkdtemp())
    os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = token_regenerate(
            str(locked / "token.txt"), default_token_file=locked / "d.txt"
        )
        assert result["ok"] is False
        assert "note" not in result
        assert "token" not in result, (
            "a failed rotation must not hand back a token that was never "
            "written -- the caller would start using a credential the "
            "bridge does not know"
        )
    finally:
        os.chmod(locked, stat.S_IRWXU)


@pytest.mark.parametrize("phrase", _FALSE_PROMISES)
def test_the_dashboard_does_not_repeat_the_false_promise(phrase):
    text = DASHBOARD_JS.read_text(encoding="utf-8").lower()
    assert phrase not in text, (
        f"dashboard still tells the operator {phrase!r}"
    )


def test_the_dashboard_saves_the_new_token_before_offering_a_choice():
    """Cancel used to leave the page holding a dead credential.

    The rotation has already happened by the time either dialog is shown,
    so the stored token is stale the instant the response arrives. Saving
    it only on the restart branch meant "Cancel" produced a dashboard that
    401'd on every subsequent call with no explanation.
    """
    text = DASHBOARD_JS.read_text(encoding="utf-8")
    save_at = text.find("localStorage.setItem(\"arena_token\"")
    choice_at = text.find("wantRestart")
    assert save_at != -1, "the dashboard no longer persists the new token"
    assert choice_at != -1
    assert save_at < choice_at, (
        "the new token must be persisted BEFORE the operator is offered a "
        "choice, because the old one is already refused"
    )


def test_the_dashboard_says_the_old_token_is_already_dead():
    text = DASHBOARD_JS.read_text(encoding="utf-8").lower()
    assert "immediately" in text or "already active" in text, (
        "the operator has to be told the rotation is already in force"
    )


def test_no_source_file_repeats_the_false_promise():
    """Catch the claim wherever it is copied next.

    Two places said it; the third copy is the one that gets missed.
    """
    offenders: list[str] = []
    for path in REPO.rglob("*"):
        if path.is_dir() or ".git" in path.parts:
            continue
        if path.suffix not in {".py", ".js", ".md", ".html", ".ts"}:
            continue
        if path.name == pathlib.Path(__file__).name:
            continue
        # CHANGELOG entries quote the old wording on purpose.
        if path.name.startswith("CHANGELOG"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if re.search(r"old token until the bridge restarts", text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "these files still claim the old token survives a rotation: "
        + ", ".join(offenders)
    )
