"""The Termux installer must stay safe and must stay honest.

A phone is not a desktop. It roams between untrusted networks, so the
one thing this installer must never do is casually bind an owner-shell
bridge to every interface. It also must not claim success before the
bridge has been shown to import on the device -- "green != works"
applies hardest on a platform CI cannot reach.

These are static checks on the script text plus a real execution
against a simulated Termux tree. They exist because the phone itself is
not available to CI, so the alternative detector is the operator
discovering it in a coffee shop.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_termux.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_installer_exists_and_is_executable():
    assert SCRIPT.is_file(), "scripts/install_termux.sh is missing"
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "installer is not executable"


def test_it_never_binds_to_every_interface_by_default():
    """The security property, asserted on the command it actually runs.

    An owner-shell bridge on 0.0.0.0 on public Wi-Fi is a remote shell
    handed to whoever shares the network. The default must be loopback;
    widening is the operator's explicit decision, over Tailscale.
    """
    text = _text()
    run_line = [ln for ln in text.splitlines() if ln.startswith("RUN_CMD=")]
    assert run_line, "RUN_CMD not found -- did the script change shape?"
    assert "--bind 127.0.0.1" in run_line[0], (
        f"default run command does not bind to loopback: {run_line[0]}")
    assert "0.0.0.0" not in run_line[0], (
        "the default run command binds to every interface")


def test_it_warns_about_binding_widely():
    """Refusing silently teaches nothing; the script must say why."""
    text = _text()
    assert "0.0.0.0" in text, "no mention of the wide-bind hazard at all"
    assert "Tailscale" in text, "no safe alternative offered"


def test_it_verifies_the_bridge_imports_before_claiming_success():
    """Green != works: the install must prove itself on the device."""
    text = _text()
    assert "import unified_bridge" in text, (
        "installer never checks that the bridge imports on the phone")
    assert "hostplatform" in text, (
        "installer never confirms it is actually on Android")


def test_it_refuses_to_run_outside_termux():
    text = _text()
    assert "PREFIX" in text and "ANDROID_ROOT" in text, (
        "installer does not check it is running on a phone")
    assert "set -euo pipefail" in text, "script does not fail closed"


def test_psutil_is_optional_and_aiohttp_is_not():
    """The dependency story is what makes on-device viable at all.

    aiohttp is the single hard requirement; psutil must degrade. If a
    future edit makes psutil mandatory, Termux installs start failing on
    devices where it will not build.
    """
    text = _text()
    assert "aiohttp" in text

    # Scope the check to the psutil install block itself. An earlier
    # draft searched a fixed number of characters after the first
    # mention of "psutil" and tripped over a `die` belonging to the
    # next section entirely -- a false positive, which is the one
    # failure mode a gate must not have.
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if "pip install" in ln and "psutil" in ln]
    assert starts, "the installer no longer installs psutil at all"
    block = lines[starts[0]:starts[0] + 6]

    assert not any("die " in ln for ln in block), (
        "a psutil failure now aborts the install; it must degrade:\n"
        + "\n".join(block))
    assert any("psutil" in ln and "optional" in ln.lower()
               for ln in lines), "psutil is no longer described as optional"

    # aiohttp, by contrast, must remain fatal -- the bridge cannot run
    # without it, and a "successful" install that cannot serve is worse
    # than a failed one.
    aiohttp_lines = [ln for ln in lines if "aiohttp install failed" in ln]
    assert aiohttp_lines, "an aiohttp failure no longer aborts the install"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_the_script_is_syntactically_valid():
    result = subprocess.run(["bash", "-n", str(SCRIPT)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_it_runs_end_to_end_against_a_simulated_termux(tmp_path):
    """Execute it, do not just read it.

    Builds a fake Termux tree -- a `com.termux` PREFIX, stub `pkg` and
    `pip` on PATH, ANDROID_ROOT set -- and runs the real script against
    a real copy of the bridge. This is the closest thing to a phone that
    CI can offer, and it caught a duplicated `--bind` flag in the
    Tailscale hint that reading the script had missed.
    """
    prefix = tmp_path / "com.termux" / "files" / "usr"
    binaries = prefix / "bin"
    binaries.mkdir(parents=True)
    for stub in ("pkg", "pip"):
        path = binaries / stub
        path.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    bridge_dir = tmp_path / "arena-bridge"
    bridge_dir.mkdir()
    (bridge_dir / "unified_bridge.py").write_text(
        (ROOT / "unified_bridge.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    shutil.copytree(ROOT / "arena", bridge_dir / "arena",
                    ignore=shutil.ignore_patterns("__pycache__"))

    env = dict(os.environ)
    env.update({
        "PREFIX": str(prefix),
        "ANDROID_ROOT": "/system",
        "ANDROID_DATA": "/data",
        "HOME": str(tmp_path),
        "ARENA_BRIDGE_DIR": str(bridge_dir),
        "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
    })

    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True,
                            text=True, env=env, cwd=str(bridge_dir),
                            timeout=300)
    assert result.returncode == 0, (
        f"installer failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    # It must have detected Android, not merely finished.
    assert "host class : android" in result.stdout, result.stdout
    assert "role       : on-device" in result.stdout, result.stdout

    # A token must exist and be owner-only.
    token_file = bridge_dir / "token.txt"
    assert token_file.is_file(), "no token generated"
    assert token_file.read_text(encoding="utf-8").strip().startswith("qaz_")
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600, (
        "token file is not owner-only")

    # And no suggested command may bind wide.
    for line in result.stdout.splitlines():
        if "unified_bridge.py serve" in line:
            assert "0.0.0.0" not in line, f"wide bind suggested: {line}"
            # A malformed hint (two --bind flags) would not run.
            assert line.count("--bind") <= 1, f"duplicated --bind: {line}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_it_refuses_a_non_termux_host(tmp_path):
    """Reverse sabotage: running this on a desktop must abort, not proceed."""
    env = dict(os.environ)
    env.pop("PREFIX", None)
    env.pop("ANDROID_ROOT", None)
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True,
                            text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert result.returncode != 0, "installer ran happily on a non-phone"
    assert "Termux" in result.stderr or "Termux" in result.stdout
