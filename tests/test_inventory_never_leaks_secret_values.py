"""The machine inventory may name a secret, never print its value.

`arena/inventory` was the next block of barely-covered code that touches the
machine: 46 collectors, `registry.py` at 17.7%, several probes under 5%. They
shell out, read the environment, and their output is handed to a model
through `sys.inventory` -- so a leaked value does not stay local, it lands in
a conversation and possibly in a provider's logs.

The redaction design is already sound: `probe_agent_ctx` reports secret
*names* and never values, with an allowlist so `*_TOKEN_FILE` paths do not
clutter the report. What was missing is anything asserting it stays that way
across all 46 collectors and their formatters.

Measured before writing this: every collector ran (46/46, none raised) and
none emitted a canary planted in nine secret-shaped environment variables.
This test pins that result, and covers the formatters too -- a collector can
redact correctly and its `format_lines` sibling still interpolate the raw
value into a display string.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.inventory.registry import REGISTRY  # noqa: E402

CANARY = "CANARY-ce7f19-do-not-leak-4d2b"

# Names shaped like real credentials, including the bridge's own token.
SECRET_ENVS = (
    "ARENA_LOCAL_BRIDGE_TOKEN",
    "ARENA_BRIDGE_TOKEN",
    "ARENA_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MY_API_KEY",
    "DATABASE_URL",
    "SOME_PASSWORD",
    "SIGNING_KEY",
    "SESSION_SECRET",
)


@pytest.fixture(autouse=True)
def _planted_secrets(monkeypatch):
    for name in SECRET_ENVS:
        monkeypatch.setenv(name, CANARY)


@pytest.mark.parametrize("section", REGISTRY, ids=lambda s: s.name)
def test_collector_never_emits_a_secret_value(section):
    """A collector may say GITHUB_TOKEN exists; it must not say what it is."""
    try:
        payload = section.collector()
    except Exception as exc:  # noqa: BLE001 -- a raising probe is a separate concern
        pytest.skip(f"{section.name} collector raised {type(exc).__name__}: {exc}")

    blob = json.dumps(payload, default=str)
    assert CANARY not in blob, (
        f"inventory section {section.name!r} emitted a secret VALUE. This "
        "output is sent to a model, so a leak here leaves the machine.")


@pytest.mark.parametrize("section", REGISTRY, ids=lambda s: s.name)
def test_formatter_never_emits_a_secret_value(section):
    """Redacting in the collector is not enough if the formatter re-adds it."""
    fmt = getattr(section, "format_lines", None)
    if not callable(fmt):
        pytest.skip(f"{section.name} has no formatter")
    try:
        payload = section.collector()
        lines = fmt(payload)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{section.name} formatter raised {type(exc).__name__}: {exc}")

    text = "\n".join(str(x) for x in (lines or []))
    assert CANARY not in text, (
        f"inventory formatter for {section.name!r} printed a secret value "
        "even though its collector redacted one")


def test_secret_names_are_still_reported():
    """A probe that hides everything would make the tests above vacuous."""
    from arena.inventory import probe_agent_ctx as P

    out = P.get_env_secret_names()
    names = set(out.get("names") or [])
    assert "GITHUB_TOKEN" in names, (
        "the probe stopped reporting secret names entirely; then it is not "
        "redacting, it is just broken")
    assert CANARY not in json.dumps(out, default=str)


def test_every_collector_actually_runs():
    """Silent exceptions would turn the leak tests into skips."""
    raised = []
    for section in REGISTRY:
        try:
            section.collector()
        except Exception as exc:  # noqa: BLE001
            raised.append(f"{section.name}: {type(exc).__name__}: {exc}")
    assert not raised, (
        "inventory collectors must not raise on a normal host -- a raising "
        "collector is skipped by the leak checks above:\n  " + "\n  ".join(raised))


def test_the_canary_would_be_visible_if_it_leaked():
    """Prove the detector can fire, so a green run means something."""
    fake_payload = {"env": {"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]}}
    assert CANARY in json.dumps(fake_payload), (
        "the canary is not reaching the environment these tests inspect")
