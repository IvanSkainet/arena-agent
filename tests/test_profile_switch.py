"""The runtime profile switch must be reachable, deliberate, and honest.

The operator could not change the exec profile without editing a command
line and restarting the bridge -- on a phone, that means going back into
Termux, which is exactly what the Dashboard exists to avoid. His verdict:
*"I cannot coexist with restrictions... there is no button, and without
it this is unusable."*

A safety control nobody can reach does not get respected; it gets routed
around, and the workaround he asked for ("a button that grants
everything") would have been far worse than a precise one. So the
restriction moved from *impossible* to *deliberate*: widening needs
consent, narrowing does not, and everything is audited.

These tests pin all three properties, plus the reverse: that the switch
cannot be tricked into granting more than the desktop always had.
"""
from __future__ import annotations

import pytest

from arena.admin import profile_switch as ps


def _cfg(profile="cautious", bind="127.0.0.1", token="tok"):
    return {"profile": profile, "bind": bind, "token": token}


# ------------------------------------------------------------ widening

def test_widening_requires_consent():
    cfg = _cfg()
    result = ps.switch(cfg, target="owner-shell", consent=None)
    assert result["ok"] is False
    assert result["consent_required"] is True
    assert result["required_consent"].startswith("yes-owner-shell-")
    assert cfg["profile"] == "cautious", "profile changed without consent"


def test_the_correct_phrase_grants_it():
    cfg = _cfg()
    phrase = ps.switch(cfg, target="owner-shell", consent=None)["required_consent"]
    result = ps.switch(cfg, target="owner-shell", consent=phrase)
    assert result["ok"] is True
    assert result["changed"] is True
    assert cfg["profile"] == "owner-shell"


def test_a_wrong_phrase_does_not():
    cfg = _cfg()
    result = ps.switch(cfg, target="owner-shell", consent="yes-owner-shell-000")
    assert result["ok"] is False
    assert cfg["profile"] == "cautious"


def test_consent_is_bound_to_the_bind_address():
    """Bug #70's lesson: consent must name what it approves.

    A phrase obtained while the bridge was on loopback must not still
    authorise widening after it has been rebound to every interface --
    that is a materially different grant. #70 shipped an update consent
    that was not bound to the asset it approved; the same shape here
    would be worse, because the thing being granted is a shell.
    """
    cfg = _cfg(bind="127.0.0.1")
    phrase = ps.switch(cfg, target="owner-shell", consent=None)["required_consent"]

    cfg["bind"] = "0.0.0.0"  # noqa: S104 -- the scenario under test
    result = ps.switch(cfg, target="owner-shell", consent=phrase)
    assert result["ok"] is False, (
        "consent granted for a loopback bridge was accepted after the "
        "bridge was exposed to the network")
    assert cfg["profile"] == "cautious"


def test_consent_is_bound_to_the_token():
    """Two bridges must not share a phrase.

    Without the token in the derivation, the phrase would be a pure
    function of (profile, bind) -- identical on every bridge on
    127.0.0.1, and therefore precomputable by anyone who has ever seen
    one.
    """
    a = ps.switch(_cfg(token="alpha"), target="owner-shell",
                  consent=None)["required_consent"]
    b = ps.switch(_cfg(token="beta"), target="owner-shell",
                  consent=None)["required_consent"]
    assert a != b


# ----------------------------------------------------------- narrowing

def test_narrowing_needs_no_consent():
    """Friction on the way to *more* safety is how a control gets left off.

    Re-enabling restrictions must be one call, always, with no phrase to
    fetch and no dialog to satisfy.
    """
    cfg = _cfg(profile="owner-shell")
    result = ps.switch(cfg, target="cautious", consent=None)
    assert result["ok"] is True
    assert result["changed"] is True
    assert cfg["profile"] == "cautious"


def test_switching_to_the_current_profile_is_a_no_op():
    cfg = _cfg(profile="owner-shell")
    result = ps.switch(cfg, target="owner-shell", consent=None)
    assert result["ok"] is True
    assert result["changed"] is False


# -------------------------------------------------------------- limits

@pytest.mark.parametrize("bogus", ["root", "admin", "god-mode", "", "ALL",
                                   "owner_shell", "cautious "])
def test_only_the_two_real_profiles_exist(bogus):
    """Reverse sabotage: no "grant everything" level.

    The operator asked for a button that grants all permissions. There
    is nothing wider than `owner-shell` to grant -- the token already
    implies his own privileges -- so an unknown profile name must be
    refused rather than quietly treated as "maximum".
    """
    cfg = _cfg()
    result = ps.switch(cfg, target=bogus, consent=None)
    assert result["ok"] is False
    assert cfg["profile"] == "cautious"

    # `ok is False` is not enough: a *consent challenge* is also False,
    # and an unknown profile that merely gets challenged would be
    # written on the second call. Sabotaging the validation produced
    # exactly that -- `required_consent: yes-god-mode-...` -- and this
    # test passed. It must be refused outright, never offered a phrase.
    assert not result.get("consent_required"), (
        f"unknown profile {bogus!r} was offered a consent phrase instead "
        f"of being refused; echoing it back would set it")
    assert "error" in result

    # And the second step must refuse too, whatever phrase is supplied.
    forced = ps.switch(cfg, target=bogus,
                       consent=result.get("required_consent") or "anything")
    assert forced["ok"] is False
    assert cfg["profile"] == "cautious", (
        f"unknown profile {bogus!r} was written to the config")


def test_describe_warns_when_exposed_to_the_network():
    exposed = ps.describe(_cfg(bind="0.0.0.0"))  # noqa: S104
    assert exposed["network_exposed"] is True
    assert exposed["warning"]

    local = ps.describe(_cfg(bind="127.0.0.1"))
    assert local["network_exposed"] is False
    assert local["warning"] is None


def test_describe_explains_both_profiles_in_words():
    """A UI showing two opaque words makes the operator guess."""
    described = ps.describe(_cfg())
    for name in ps.PROFILES:
        assert described["meaning"].get(name), f"{name} has no explanation"


# --------------------------------------------------------------- wiring

def test_the_endpoints_are_registered():
    from arena.route_registry import registry

    source = registry.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "handle_v1_admin_profile_get" in text
    assert "handle_v1_admin_profile_post" in text


def test_the_dashboard_exposes_a_button():
    """The whole point was reachability. Assert the UI exists.

    Checking the asset rather than trusting that someone wired it: the
    endpoint without a button leaves the operator exactly where he
    started, back in a terminal.
    """
    import pathlib

    assets = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "assets"
    script = assets / "17d-settings-profile.js"
    assert script.is_file(), "no profile switch script in the Dashboard"
    body = (assets / "body-15-settings.html").read_text(encoding="utf-8")
    assert "profileWiden()" in body, "the Settings tab has no widen button"
    assert "profileNarrow()" in body, "the Settings tab has no narrow button"


def test_every_switch_is_audited():
    """A privilege change with no trace is indistinguishable from a breach."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "arena" / "admin" / "handlers_profile.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)}
    assert "audit" in calls, "the profile handler never audits"
    assert "profile.switch" in source, "audit event is not tagged"


# ------------------------------------------------------- loopback classifier

@pytest.mark.parametrize("address", [
    "127.0.0.1",
    "127.0.0.2",      # the whole 127.0.0.0/8 block is loopback
    "127.255.255.254",
    "::1",
    "0:0:0:0:0:0:0:1",
    "localhost",
    "LOCALHOST",      # case must not matter
])
def test_loopback_addresses_are_recognised(address):
    """v4.168.3: the hand-written literal list was wrong as well as noisy.

    It listed exactly "127.0.0.1", so a bridge bound to 127.0.0.2 --
    equally unreachable from the network -- was classified as exposed
    and its consent phrase differed. Deferring to `ipaddress` fixes the
    correctness problem and removes the literals devskim was flagging
    (#320-#326) in one move.
    """
    assert ps.is_loopback(address) is True


@pytest.mark.parametrize("address", [
    "0.0.0.0",        # noqa: S104 -- the value under test
    "192.168.1.5",
    "10.5.1.2",
    "::",
    "auto",           # unresolved placeholder
    "tailscale0",     # an interface name, not an address
    "",               # absent
    "   ",
])
def test_non_loopback_addresses_are_treated_as_exposed(address):
    """Fail closed: anything not provably local is reported as exposed.

    Reporting an unparseable bind as safe is how a bridge ends up on a
    public interface while the UI says it is not -- reassurance is the
    one thing this classifier must never invent.
    """
    assert ps.is_loopback(address) is False


def test_the_classifier_has_no_hardcoded_address_list():
    """The fix is deferring to stdlib, not hiding the literals.

    A future edit that reintroduces a tuple of address strings would be
    both less correct (missing 127.0.0.0/8) and would bring the scanner
    findings back. Pin the mechanism.
    """
    import inspect

    source = inspect.getsource(ps.is_loopback)
    assert "ipaddress" in source, (
        "is_loopback no longer defers to the standard library")
    assert "127.0.0.1" not in source, (
        "a hardcoded address literal is back in the classifier")
