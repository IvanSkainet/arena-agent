"""v4.102.0 -- operator posture ("cubes") model tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.autonomy import posture as P  # noqa: E402
from arena.autonomy.posture_identity import derive_preset_name  # noqa: E402
from arena.files.sandbox import SENSITIVE_DIR_PREFIXES  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    P._reset_cache()
    yield
    P._reset_cache()


def test_default_is_strict_and_low():
    p = P.load_posture()
    assert p["sandbox"] == "systemd" and p["network"] == "deny"
    assert p["preset"] == "strict"
    assert P.risk_level(p) == "low"
    assert P.required_ack(p) is None


@pytest.mark.parametrize("name", list(P.PRESETS))
def test_every_preset_is_valid(name):
    assert P.validate_posture(P.PRESETS[name]) is None
    assert derive_preset_name(P.PRESETS[name], P.PRESETS, P.AXES) == name


def test_stale_persisted_label_cannot_claim_strict_for_naked_axes():
    path = P.store_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**P.PRESETS["naked"], "preset": "strict"}), encoding="utf-8")

    posture = P.load_posture()
    assert posture["preset"] == "naked"
    assert P.risk_level(posture) == "critical"
    assert P.get_posture()["posture"]["preset"] == "naked"


def test_non_preset_axis_tuple_is_custom():
    custom = {**P.PRESETS["strict"], "network": "allowlist"}
    assert derive_preset_name(custom, P.PRESETS, P.AXES) == "custom"


def test_duplicate_preset_definitions_fail_closed_as_custom():
    duplicated = {"first": P.PRESETS["strict"], "second": P.PRESETS["strict"]}
    assert derive_preset_name(P.PRESETS["strict"], duplicated, P.AXES) == "custom"


def test_set_posture_ignores_forged_preset_label_and_persists_identity():
    forged = {**P.PRESETS["naked"], "preset": "strict"}
    result = P.set_posture(forged, ack=P.ACK_PHRASES["critical"])
    assert result["posture"]["preset"] == "naked"
    saved = json.loads(P.store_path().read_text(encoding="utf-8"))
    assert saved["preset"] == "naked"


def test_risk_levels():
    assert P.risk_level(P.PRESETS["naked"]) == "critical"
    off = {**P.PRESETS["strict"], "sandbox": "off"}
    assert P.risk_level(off) == "high"
    assert P.risk_level(P.PRESETS["strict"]) == "low"


def test_validate_rejects_bad_axis():
    bad = {**P.PRESETS["strict"], "network": "yolo"}
    assert P.validate_posture(bad) is not None


def test_ack_required_for_risky_postures():
    assert P.required_ack(P.PRESETS["strict"]) is None
    need = P.required_ack(P.PRESETS["naked"])
    assert need == P.ACK_PHRASES["critical"]


def test_set_rejects_missing_or_wrong_ack():
    r = P.set_posture(P.PRESETS["naked"])  # no ack
    assert not r["ok"] and r["error"] == "ack_required"
    assert r["required_ack"] == P.ACK_PHRASES["critical"]
    r2 = P.set_posture(P.PRESETS["naked"], ack="nope")
    assert not r2["ok"] and r2["error"] == "ack_required"


def test_set_accepts_correct_ack_and_persists():
    r = P.set_posture(P.PRESETS["naked"], ack=P.ACK_PHRASES["critical"])
    assert r["ok"] and r["risk"] == "critical"
    P._reset_cache()
    assert P.load_posture()["sandbox"] == "off"


def test_set_rejects_invalid_posture():
    assert not P.set_posture({"sandbox": "bogus"})["ok"]


def test_autonomy_dir_is_on_sensitive_blocklist():
    # so the agent's fs API cannot read/edit the operator posture
    assert "autonomy" in SENSITIVE_DIR_PREFIXES


def test_get_posture_exposes_axes_and_ack_phrases_for_ui():
    g = P.get_posture()
    assert g["ok"] is True  # UI guards on this; must be present (v4.103.1 fix)
    assert set(g["axes"]) == set(P.AXES)
    assert g["axes"]["sandbox"] == P.SANDBOX_VALUES
    assert g["ack_phrases"] == P.ACK_PHRASES
    assert set(g["presets"]) == set(P.PRESETS)
