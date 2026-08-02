"""Provider-agnostic emulator control and the capability gap tracker.

Green here does not mean an emulator boots. These tests pin *contracts*:
argv shapes, refusal paths, and the fact that no vendor is hardcoded into
a code path. Real booting is verified by execution on a host that has the
manager installed -- see docs/emulators.md.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import capability_gaps  # noqa: E402
from arena.emulator import control, providers  # noqa: E402
from arena.mcp.tool_emulator import handle_emulator_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _text(res):
    return json.loads(res["content"][0]["text"])


# ---------------------------------------------------------------------------
# capability gaps (unchanged behaviour, kept alongside its historical peer)
# ---------------------------------------------------------------------------

def test_capability_gap_record_list_resolve(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    rec = capability_gaps.record(
        title="Need emulator provider for X",
        evidence={"err": "unknown_provider"},
        suggested_tool="emulator.providers",
    )
    assert rec["ok"] is True
    gap_id = rec["gap"]["id"]
    listed = capability_gaps.list_gaps(status="open")
    assert listed["count"] == 1
    assert listed["gaps"][0]["suggested_tool"] == "emulator.providers"
    resolved = capability_gaps.resolve(gap_id=gap_id, resolution="implemented")
    assert resolved["ok"] is True
    assert capability_gaps.list_gaps(status="open")["count"] == 0


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def test_emulator_tools_registered():
    names = {t["name"] for t in MCP_TOOLS}
    for name in [
        "emulator.providers", "emulator.list", "emulator.start",
        "emulator.stop", "emulator.attach",
        "capability_gap.record", "capability_gap.list", "capability_gap.resolve",
    ]:
        assert name in names


def test_vendor_namespace_is_gone():
    """The vendor-locked mumu.* namespace must not come back as a tool name."""
    names = {t["name"] for t in MCP_TOOLS}
    assert not [n for n in names if n.startswith("mumu.")]
    assert not (REPO / "arena" / "mcp" / "tool_mumu.py").exists()


def test_no_operator_home_directory_is_hardcoded():
    """Guard against the original sin: a specific user's path in a default.

    The old mumu.screenshot defaulted to C:\\Users\\Ivan\\... . Any provider
    or emulator module reintroducing a concrete user home fails here.
    """
    offenders = []
    for path in sorted((REPO / "arena" / "emulator").rglob("*.py")) + [REPO / "arena" / "mcp" / "tool_emulator.py"]:
        text = path.read_text(encoding="utf-8")
        for marker in ("C:\\Users\\Ivan", "C:/Users/Ivan", "/home/ivan", "/Users/ivan"):
            if marker.lower() in text.lower():
                offenders.append(f"{path.relative_to(REPO)}: {marker}")
    assert offenders == []


# ---------------------------------------------------------------------------
# provider table: data, not code
# ---------------------------------------------------------------------------

def test_builtin_providers_cover_more_than_one_vendor_and_os():
    ids = {p.id for p in providers.BUILTIN_PROVIDERS}
    assert {"avd", "genymotion", "mumu", "waydroid"} <= ids
    # No provider may be the only one for a mainstream OS.
    for system in ("windows", "linux", "darwin"):
        supported = [p for p in providers.BUILTIN_PROVIDERS if not p.os or system in p.os]
        assert len(supported) >= 2, f"{system} has too few providers: {supported}"


def test_every_provider_declares_at_least_a_start_path():
    for prov in providers.BUILTIN_PROVIDERS:
        assert prov.start_argv, f"{prov.id} cannot start anything"
        assert prov.binary_names or prov.binary_env, f"{prov.id} is unlocatable"


def test_detect_reports_unsupported_provider_on_foreign_os():
    rows = {r["id"]: r for r in providers.detect_providers(host_os="Linux")}
    assert rows["mumu"]["supported_on_host"] is False
    assert rows["mumu"]["available"] is False
    assert rows["waydroid"]["supported_on_host"] is True
    rows_win = {r["id"]: r for r in providers.detect_providers(host_os="Windows")}
    assert rows_win["waydroid"]["supported_on_host"] is False
    assert rows_win["mumu"]["supported_on_host"] is True


def test_host_can_declare_its_own_provider_without_code(monkeypatch, tmp_path):
    fake = tmp_path / "myemu"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("MYEMU_BIN", str(fake))
    monkeypatch.setenv(providers.PROVIDERS_ENV, json.dumps([{
        "id": "myemu",
        "label": "In-house emulator",
        "binary_env": "MYEMU_BIN",
        "list_argv": ["ls"],
        "start_argv": ["up", "{id}"],
    }]))
    rows = {r["id"]: r for r in providers.detect_providers()}
    assert rows["myemu"]["available"] is True
    assert rows["myemu"]["binary"] == str(fake)
    # and the builtins survive the merge
    assert "avd" in rows


def test_host_entry_overrides_a_builtin_by_id(monkeypatch, tmp_path):
    fake = tmp_path / "patched-mumu"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv(providers.PROVIDERS_ENV, json.dumps([{
        "id": "mumu",
        "label": "MuMu (corrected path)",
        "os": ["linux", "windows"],
        "binary_env": "PATCHED_MUMU",
        "start_argv": ["go"],
    }]))
    monkeypatch.setenv("PATCHED_MUMU", str(fake))
    rows = {r["id"]: r for r in providers.detect_providers(host_os="Linux")}
    assert rows["mumu"]["label"] == "MuMu (corrected path)"
    assert rows["mumu"]["supported_on_host"] is True


@pytest.mark.parametrize("raw", ["not json", "{}", "[1, 2]", '[{"label": "no id"}]'])
def test_malformed_host_provider_config_is_ignored_not_fatal(monkeypatch, raw):
    monkeypatch.setenv(providers.PROVIDERS_ENV, raw)
    ids = {p.id for p in providers.load_providers()}
    assert {"avd", "mumu"} <= ids


def test_broken_env_pin_is_reported_not_silently_swallowed(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_MUMU_CLI", str(tmp_path / "nope.exe"))
    rows = {r["id"]: r for r in providers.detect_providers(host_os="Windows")}
    assert rows["mumu"]["broken_pin"].endswith("nope.exe")
    assert "not a file" in rows["mumu"]["hint"]


def test_unexpanded_placeholder_paths_are_skipped(monkeypatch):
    """A well-known path referencing an absent env var must not be stat'ed."""
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.delenv("ANDROID_EMULATOR", raising=False)
    prov = providers.EmulatorProvider(
        id="ghost", label="Ghost",
        well_known=("$DEFINITELY_NOT_SET_12345/bin/ghost",),
        start_argv=("go",),
    )
    assert providers.resolve_binary(prov) is None


def test_build_argv_substitutes_only_the_id_placeholder():
    prov = providers.find_provider("mumu")
    assert providers.build_argv(prov, prov.start_argv, "3") == ["control", "--vmindex", "3", "launch"]
    avd = providers.find_provider("avd")
    assert providers.build_argv(avd, avd.start_argv, "Pixel_7") == ["-avd", "Pixel_7"]


# ---------------------------------------------------------------------------
# control layer: refusals and argv assembly
# ---------------------------------------------------------------------------

def _pin(monkeypatch, tmp_path, env: str, name: str = "cli") -> Path:
    fake = tmp_path / name
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv(env, str(fake))
    return fake


def test_start_builds_provider_argv_without_a_shell(monkeypatch, tmp_path):
    fake = _pin(monkeypatch, tmp_path, "ARENA_MUMU_CLI", "mumu-cli.exe")
    seen = {}

    def fake_run(argv, timeout):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return {"ok": True, "returncode": 0, "argv": argv, "stdout": "", "stderr": ""}

    monkeypatch.setattr(control, "_run", fake_run)
    out = control.start(provider="mumu", instance="2", timeout=9)
    assert out["ok"] is True
    assert seen["argv"] == [str(fake), "control", "--vmindex", "2", "launch"]
    assert seen["timeout"] == 9
    assert "mobile.devices" in out["next"]


def test_unknown_provider_refuses_and_lists_known_ones():
    out = control.start(provider="bluestacks-9000", instance="1")
    assert out["ok"] is False
    assert out["error"] == "unknown_provider"
    assert "avd" in out["known_providers"]


def test_missing_cli_refuses_with_a_docs_hint(monkeypatch):
    monkeypatch.delenv("ARENA_MUMU_CLI", raising=False)
    monkeypatch.setattr(providers, "resolve_binary", lambda prov: None)
    monkeypatch.setattr(control, "resolve_binary", lambda prov: None)
    out = control.list_instances(provider="mumu")
    assert out["ok"] is False
    assert out["error"] == "provider_cli_not_found"
    assert "mumuplayer.com" in out["hint"]


def test_provider_without_a_stop_verb_says_so_instead_of_guessing(monkeypatch, tmp_path):
    _pin(monkeypatch, tmp_path, "ANDROID_EMULATOR", "emulator")
    out = control.stop(provider="avd", instance="Pixel_7")
    assert out["ok"] is False
    assert out["error"] == "unsupported_operation"
    assert "emu kill" in out["hint"]


def test_run_reports_a_missing_executable_rather_than_raising():
    out = control._run([str(Path("/definitely/not/here/emu")), "go"], 5)
    assert out["ok"] is False
    assert out["error"] == "executable_not_found"


def test_run_reports_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    out = control._run(["x"], 1)
    assert out["ok"] is False
    assert out["error"] == "timeout"


def test_control_never_uses_shell_true():
    """Sabotage guard: a shell=True here would reopen command injection."""
    src = (REPO / "arena" / "emulator" / "control.py").read_text(encoding="utf-8")
    assert "shell=True" not in src
    assert "os.system" not in src


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------

def test_providers_tool_reports_this_host_and_points_at_mobile():
    payload = _text(handle_emulator_tool("emulator.providers", {}, ctx=object()))
    assert payload["ok"] is True
    assert payload["count"] >= 4
    ids = {r["id"] for r in payload["providers"]}
    assert "avd" in ids
    assert "mobile." in payload["note"]
    host = platform.system().lower()
    assert all(r["host_os"] == host for r in payload["providers"])


@pytest.mark.parametrize("tool", ["emulator.list", "emulator.start", "emulator.stop"])
def test_tools_require_a_provider(tool):
    payload = _text(handle_emulator_tool(tool, {}, ctx=object()))
    assert payload["ok"] is False
    assert payload["error"] == "provider is required"
    assert "emulator.providers" in payload["hint"]


def test_handler_declines_foreign_tool_names():
    assert handle_emulator_tool("mobile.devices", {}, ctx=object()) is None
    assert handle_emulator_tool("mumu.launch", {}, ctx=object()) is None


def test_attach_delegates_to_the_mobile_domain(monkeypatch):
    import arena.mobile.devices as devices

    monkeypatch.setattr(devices, "list_devices", lambda: {
        "ok": True, "adb_installed": True,
        "devices": [{"serial": "emulator-5554", "state": "device"},
                    {"serial": "R58N1234", "state": "device"}],
    })
    payload = _text(handle_emulator_tool("emulator.attach", {"serial_hint": "emulator-"}, ctx=object()))
    assert payload["ok"] is True
    assert [d["serial"] for d in payload["devices"]] == ["emulator-5554"]
    assert "mobile.shell" in payload["next"]


def test_attach_reports_no_devices_without_hanging(monkeypatch):
    import arena.mobile.devices as devices

    monkeypatch.setattr(devices, "list_devices", lambda: {"ok": True, "adb_installed": True, "devices": []})
    payload = _text(handle_emulator_tool("emulator.attach", {"wait_s": 0}, ctx=object()))
    assert payload["ok"] is False
    assert payload["devices"] == []
