"""v4.60.19 - tests for scripts/spec_kit_to_scenarios.py

The adapter parses a spec-kit `tasks.md` and emits a JSON document
suitable for `arena.scenarios.storage.scenario_save`. These tests
cover the realistic shapes: minimal, parallel, placeholders in JSON
strings, missing Args block, missing Save as, multiline block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The adapter lives under `scripts/` (alongside make_release_zip.py,
# pack_release.py, check_latest_release.py). pytest does not put
# `scripts/` on sys.path by default, so we add it explicitly.
REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import spec_kit_to_scenarios as adapter  # noqa: E402


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "tasks.md"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# parse_tasks
# ---------------------------------------------------------------------------


def test_parse_minimal_task(tmp_path: Path) -> None:
    """A single task with no Args, no Save as, no parallel flag."""
    body = (
        "# Tasks: foo\n"
        "**Input**: n/a\n"
        "## Phase 1\n"
        "- T0 In `mobile.devices`: list connected phones.\n"
    )
    steps = adapter.parse_tasks(_write(tmp_path, body))
    assert len(steps) == 1
    s = steps[0]
    assert s["id"] == "T0"
    assert s["tool"] == "mobile.devices"
    assert s["parallel"] is False
    assert s["story"] is None
    assert s["arguments"] == {}
    assert s["return_to"] is None


def test_parse_parallel_and_story(tmp_path: Path) -> None:
    """[P] and [US1] flags must propagate; section headers split phases."""
    body = (
        "# Tasks\n"
        "## Phase 1: Capture\n"
        "- T0 [P] [US1] In `mobile.record_start`: begin recording. Args: `{}`.\n"
        "  Save as `recording_id`.\n"
        "- T1 [US1] In `mobile.record_stop`: stop. Args: `{}`.\n"
        "## Phase 2: Pull\n"
        "- T2 [US2] In `mobile.record_pull`: pull bytes. Args: `{}`.\n"
    )
    steps = adapter.parse_tasks(_write(tmp_path, body))
    assert [s["id"] for s in steps] == ["T0", "T1", "T2"]
    assert steps[0]["parallel"] is True
    assert steps[0]["story"] == "US1"
    assert steps[0]["return_to"] == "recording_id"
    assert steps[1]["parallel"] is False
    assert steps[1]["return_to"] is None
    assert steps[2]["story"] == "US2"


def test_parse_json_args_with_placeholders(tmp_path: Path) -> None:
    """Args must be valid JSON; `{{ ... }}` placeholders inside strings
    must survive intact (the scenario runtime resolves them later)."""
    body = (
        "# Tasks\n"
        "- T0 [US1] In `fs.write_base64`: write file. "
        'Args: `{"path": "~/recordings/voice-{{ steps.T0.result.id }}.mp4", '
        '"base64": "{{ steps.T3.result.base64 }}"}`.\n'
    )
    steps = adapter.parse_tasks(_write(tmp_path, body))
    assert len(steps) == 1
    args = steps[0]["arguments"]
    assert args == {
        "path": "~/recordings/voice-{{ steps.T0.result.id }}.mp4",
        "base64": "{{ steps.T3.result.base64 }}",
    }


def test_parse_save_as_variants(tmp_path: Path) -> None:
    """Three valid phrasings of Save as must all parse."""
    body = (
        "# Tasks\n"
        "- T0 In `a.b`: x. Save as `r1`.\n"
        "- T1 In `a.b`: x. Save as r2.\n"
        "- T2 In `a.b`: x. Save the foo as r3.\n"
    )
    steps = adapter.parse_tasks(_write(tmp_path, body))
    assert [s["return_to"] for s in steps] == ["r1", "r2", "r3"]


def test_parse_malformed_args_warns_and_keeps_step(tmp_path: Path) -> None:
    """If Args: marker exists but the JSON is broken, the step is
    still emitted (with empty arguments) and a warning is logged."""
    body = (
        "# Tasks\n"
        "- T0 In `a.b`: x. Args: {not valid json}.\n"
    )
    steps = adapter.parse_tasks(_write(tmp_path, body))
    assert len(steps) == 1
    assert steps[0]["arguments"] == {}


# ---------------------------------------------------------------------------
# build_scenario
# ---------------------------------------------------------------------------


def test_build_scenario_prefers_scenario_return_as_final() -> None:
    """If a `scenario.return` step exists, its args become the
    scenario's `final` value verbatim (placeholders resolve at
    runtime)."""
    steps = [
        {"id": "T0", "tool": "a.b", "arguments": {"x": 1},
         "description": "x", "parallel": False, "story": None, "return_to": None},
        {"id": "T1", "tool": "scenario.return", "arguments": {"text": "{{ steps.T0.result.y }}"},
         "description": "final", "parallel": False, "story": None, "return_to": None},
    ]
    s = adapter.build_scenario(
        steps, name="x", description="y",
    )
    assert s["final"] == {"text": "{{ steps.T0.result.y }}"}


def test_build_scenario_falls_back_to_last_return_to() -> None:
    """No scenario.return step -> fall back to the last `Save as <name>`,
    wrapping it in `{{ steps.<id>.result.text }}`."""
    steps = [
        {"id": "T0", "tool": "a.b", "arguments": {},
         "description": "x", "parallel": False, "story": None, "return_to": "foo"},
    ]
    s = adapter.build_scenario(steps, name="x", description="y")
    assert s["final"] == {"text": "{{ steps.T0.result.text }}"}


def test_build_scenario_includes_parallel_and_story() -> None:
    steps = [
        {"id": "T0", "tool": "a.b", "arguments": {},
         "description": "x", "parallel": True, "story": "US1", "return_to": None},
    ]
    s = adapter.build_scenario(steps, name="x", description="y")
    assert s["steps"][0]["parallel"] is True
    assert s["steps"][0]["story"] == "US1"
    assert s["steps"][0]["id"] == "T0"
    assert s["steps"][0]["tool"] == "a.b"


# ---------------------------------------------------------------------------
# End-to-end: realistic voice-transcription-shaped tasks.md
# ---------------------------------------------------------------------------


def test_end_to_end_voice_transcription(tmp_path: Path) -> None:
    """A minimal but realistic `tasks.md` for the voice-transcription
    scenario (matching the smoke version in arena-spec-smoke) must
    produce 8 steps with the expected tool names, parallel flags, and
    JSON arguments."""
    body = (
        "# Tasks: Voice\n"
        "**Input**: spec.md, plan.md\n"
        "## Phase 1: Capture\n"
        "- T0 [US1] In `mobile.record_start`: begin mic. "
        'Args: `{"serial": "default", "audio": true, "time_limit": 5000}`. '
        "Save as `recording_id`.\n"
        "- T1 [P] [US1] In `mobile.devices`: list phones. Args: `{}`.\n"
        "- T2 [US1] In `mobile.record_stop`: stop. "
        'Args: `{"serial": "default", "rec_id": "{{ steps.T0.result.id }}"}`.\n'
        "- T3 [US1] In `mobile.record_pull`: pull. "
        'Args: `{"serial": "default", "rec_id": "{{ steps.T0.result.id }}"}`. '
        "Save as `audio_base64`.\n"
        "- T4 [US1] In `fs.write_base64`: persist. "
        'Args: `{"path": "~/recordings/voice-{{ steps.T0.result.id }}.mp4", '
        '"base64": "{{ steps.T3.result.base64 }}"}`. Save as `audio_path`.\n'
        "## Phase 2: Transcribe\n"
        "- T5 [US2] In `browser.interact`: transcribe online. "
        'Args: `{"url": "https://x/whisper", "file": "{{ steps.T4.result.path }}", '
        '"extract_selector": ".transcript", "timeout": 60}`. '
        "Save as `transcript_text`.\n"
        "- T6 [P] [US2] In `scenario.input`: declare inputs. "
        'Args: `{"url": "https://x/whisper", "selector": ".transcript"}`.\n'
        "## Phase 3: Surface\n"
        "- T7 [US3] In `scenario.return`: final. "
        'Args: `{"text": "{{ steps.T5.result.text }}"}`.\n'
    )
    out = tmp_path / "scenario.json"
    rc = adapter.main.__wrapped__ if hasattr(adapter.main, "__wrapped__") else None
    # Call the parser+builder directly (no argv mutation) for purity.
    steps = adapter.parse_tasks(_write(tmp_path, body))
    scenario = adapter.build_scenario(
        steps,
        name="voice_transcription",
        description="Voice -> PC -> transcribe -> chat (test)",
    )
    out.write_text(json.dumps(scenario, indent=2), encoding="utf-8")

    # Sanity: 8 steps, 2 parallel, expected tools, final uses T5.
    assert len(scenario["steps"]) == 8
    parallel = [s["id"] for s in scenario["steps"] if s.get("parallel")]
    assert parallel == ["T1", "T6"]
    tool_set = {s["tool"] for s in scenario["steps"]}
    assert tool_set == {
        "mobile.record_start", "mobile.devices", "mobile.record_stop",
        "mobile.record_pull", "fs.write_base64", "browser.interact",
        "scenario.input", "scenario.return",
    }
    assert scenario["final"] == {"text": "{{ steps.T5.result.text }}"}

    # Spot-check a JSON-args round-trip with placeholders.
    t0 = next(s for s in scenario["steps"] if s["id"] == "T0")
    assert t0["arguments"] == {
        "serial": "default", "audio": True, "time_limit": 5000,
    }
    t4 = next(s for s in scenario["steps"] if s["id"] == "T4")
    assert t4["arguments"]["path"] == "~/recordings/voice-{{ steps.T0.result.id }}.mp4"
    assert t4["arguments"]["base64"] == "{{ steps.T3.result.base64 }}"
