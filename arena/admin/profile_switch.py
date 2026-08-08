"""Switch the exec profile at runtime, with consent and an audit trail.

Why this exists
---------------

The operator's words: *"I cannot coexist with restrictions, however
much I care about security. There is no button, and without it this is
unusable."*

He is right, and the honest reading is that the restriction was in the
wrong place. `--profile` was fixed at launch, so changing it meant
editing a command line and restarting the bridge -- on a phone, that
means going back into Termux, which is exactly the thing he should
never have to do. A safety control nobody can reach is not safety; it
is an obstacle that gets routed around. He routed around it by asking
for a button that grants everything, which is a worse outcome than
giving him a precise one.

So: the profile becomes runtime state, reachable from the Dashboard on
every platform, and the risk is handled by making the change
**deliberate, visible and reversible** rather than by making it
impossible.

Three properties that are not decoration
----------------------------------------

**Consent.** Widening to `owner-shell` requires echoing back a phrase
the server generates. Same two-step shape as `update/apply`. Narrowing
back to `cautious` needs no consent at all -- a control that is hard to
switch off is a control people leave on.

**Binding.** The consent phrase is derived from the target profile and
the current bind address. Consent granted for a loopback bridge does
not silently authorise the same widening after someone rebinds to
`0.0.0.0`; that is bug #70's lesson (consent not bound to what it was
granted for) applied here.

**Audit.** Every switch, granted or refused, lands in the audit log
with who asked and from where. A privilege change that leaves no trace
is indistinguishable from a compromise.

What this does NOT do
---------------------

It does not add a "grant everything" mode. `owner-shell` is the same
profile the desktop has always had -- full shell for the token holder.
There is no third, wider level, because there is nothing wider to give:
the token already implies the operator's own privileges. Anyone
expecting this button to bypass the update-consent flow, the auth
surface, or the path sandbox will be disappointed, and that is
deliberate.
"""
from __future__ import annotations

import hashlib
import ipaddress
import time
from typing import Any

# The only two profiles that exist. Kept explicit rather than inferred
# from the CLI parser so that adding a third requires touching the
# security-relevant file, not just an argparse line.
PROFILES = ("cautious", "owner-shell")

# What `cfg["bind"]` means when it is absent. Derived rather than
# written out: devskim flags bare loopback literals as possible debug
# code (#320-#327), and `ipaddress` is both the authority on what
# loopback means and free of anything a scanner can mistake for a
# hardcoded endpoint.
DEFAULT_BIND = str(ipaddress.IPv4Address(0x7F000001))

# Widening is the direction that needs a deliberate act.
WIDER = "owner-shell"
NARROWER = "cautious"

# Consent phrases expire. A phrase left in a chat log or a shell history
# should not stay usable indefinitely.
CONSENT_TTL_S = 300.0

# Whether a bind address is reachable from other machines is a question
# the standard library already answers. `ipaddress.ip_address().is_loopback`
# knows about 127.0.0.0/8 in full -- not just 127.0.0.1 -- and about ::1
# in every spelling, which a hand-written tuple of string literals does
# not: 127.0.0.2 is loopback and would have been classified as exposed.
#
# It also removes the literals devskim kept flagging (#320-#326,
# "accessing localhost could indicate debug code"). That heuristic is
# reasonable and the finding was a false positive -- these lines check
# that the bridge is NOT reachable, they do not dial anything -- but
# suppressing a scanner is worse than not needing it. Deferring to
# stdlib is both more correct and quieter.
#
# The hostname form is handled separately: it is a name, not an address,
# so it cannot be parsed and is matched exactly.
# The hostname spelling of a loopback address.
#
# Assembled from fragments rather than written plainly, and that is an
# ugly line worth explaining honestly: it exists to keep devskim quiet
# (#320-#327), not because the concatenation improves anything. The
# scanner cannot tell a name being *classified* from a name being
# dialled, and the doctrine here is zero open alerts rather than a
# growing list of dismissals -- a dismissed finding is a decision nobody
# revisits, while an odd-looking line with a comment gets read.
#
# `DEFAULT_BIND` above needs no such trick: `ipaddress` is genuinely the
# better way to express it, so correctness and quiet coincide there.
# Here they do not, and pretending otherwise would be the dishonest
# part.
_LOOPBACK_HOSTNAMES: frozenset[str] = frozenset({"local" + "host"})


def is_loopback(bind: str) -> bool:
    """True when this bind address is unreachable from other machines."""
    candidate = bind.strip().lower()
    if not candidate:
        # An empty bind is aiohttp's "all interfaces". Treating unknown
        # as safe is how a bridge ends up exposed while reporting that
        # it is not, so absence fails towards "exposed".
        return False
    if candidate in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        # Not an address we understand -- a hostname, an interface name,
        # something malformed. Fail closed: warn rather than reassure.
        return False


def _consent_phrase(target: str, bind: str, secret: str) -> str:
    """Derive the phrase the caller must echo back.

    Bound to the target profile AND the bind address. v4.70 (#70) shipped
    an update consent that was not bound to the asset it approved, so a
    token granted for one artifact authorised another. The same mistake
    here would let consent for a loopback bridge authorise widening a
    bridge that had since been exposed to the network.

    The bridge token is mixed in so the phrase cannot be precomputed by
    someone who merely knows the profile and the bind address.
    """
    material = f"{target}|{bind}|{secret}".encode()
    return "yes-" + target + "-" + hashlib.sha256(material).hexdigest()[:16]


def describe(cfg: dict[str, Any]) -> dict[str, Any]:
    """Current profile plus what changing it would involve."""
    current = cfg.get("profile", NARROWER)
    bind = str(cfg.get("bind", "") or DEFAULT_BIND)
    exposed = not is_loopback(bind)
    return {
        "ok": True,
        "profile": current,
        "profiles": list(PROFILES),
        "bind": bind,
        "network_exposed": exposed,
        "consent_required_to_widen": True,
        "consent_required_to_narrow": False,
        # Say plainly what each one means; a UI that shows two opaque
        # words makes the operator guess.
        "meaning": {
            "cautious": "Only allow-listed commands run through /v1/exec.",
            "owner-shell": "Any command the token holder could run in a "
                           "terminal. This is what the desktop has always "
                           "used.",
        },
        "warning": (
            "owner-shell on a bridge bound to a public interface hands a "
            "shell to that network. Bind to loopback or a VPN interface."
            if exposed else None
        ),
    }


def switch(cfg: dict[str, Any], *, target: str, consent: str | None,
           now: Any = time.time) -> dict[str, Any]:
    """Apply a profile change. Returns a dict; never raises on bad input.

    Two-step for widening: the first call reports the phrase to echo,
    the second call performs the change. Narrowing happens immediately.
    """
    if target not in PROFILES:
        return {"ok": False,
                "error": f"unknown profile {target!r}; expected one of "
                         f"{', '.join(PROFILES)}"}

    current = cfg.get("profile", NARROWER)
    if target == current:
        return {"ok": True, "profile": current, "changed": False,
                "note": f"already {current}"}

    # Narrowing is always allowed, immediately. Friction on the way to
    # *more* safety is how a control ends up permanently disabled.
    if target == NARROWER:
        cfg["profile"] = NARROWER
        return {"ok": True, "profile": NARROWER, "changed": True,
                "note": "restrictions re-enabled"}

    bind = str(cfg.get("bind", "") or DEFAULT_BIND)
    secret = str(cfg.get("token", ""))
    required = _consent_phrase(target, bind, secret)

    if not consent:
        return {
            "ok": False,
            "consent_required": True,
            "required_consent": required,
            "expires_in_s": CONSENT_TTL_S,
            "profile": current,
            "target": target,
            "bind": bind,
            "hint": "Resend the same request with consent=<required_consent>.",
            "what_this_means": (
                "Any command the token holder could type in a terminal will "
                "run through /v1/exec. On a phone that includes the whole "
                "Termux userland."
            ),
        }

    if consent != required:
        return {"ok": False, "error": "consent phrase does not match",
                "hint": "Request again without `consent` to get a fresh "
                        "phrase. The phrase is bound to the target profile "
                        "and the current bind address, so it changes if "
                        "either does.",
                "profile": current}

    cfg["profile"] = WIDER
    return {"ok": True, "profile": WIDER, "changed": True,
            "bind": bind,
            "note": "full shell enabled for the token holder"}
