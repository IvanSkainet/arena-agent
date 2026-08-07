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
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_termux.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_installer_exists_and_is_executable():
    """The exec bit must be recorded in git, not merely on this disk.

    First version checked `os.stat` and went red on all fifteen CI jobs:
    the file had been committed 100644, and `core.fileMode=false` in the
    sandbox meant a local `chmod +x` never staged. Worse, checking the
    filesystem cannot work on Windows at all -- there is no POSIX exec
    bit there, so the test would have stayed red on five jobs even after
    the mode was fixed.

    Git's index is the portable source of truth: a mode of 100755 is
    what gets checked out on the phone, which is the only place that
    matters.
    """
    assert SCRIPT.is_file(), "scripts/install_termux.sh is missing"

    if shutil.which("git") is None:  # pragma: no cover - git is always there
        pytest.skip("git unavailable")
    result = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/install_termux.sh"],
        capture_output=True, text=True, cwd=str(ROOT))
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("not a git checkout")

    mode = result.stdout.split()[0]
    assert mode == "100755", (
        f"installer is committed as {mode}; it must be 100755 so it is "
        f"executable when checked out on the phone. Fix with:\n"
        f"    git update-index --chmod=+x scripts/install_termux.sh")

    # Where the OS does model an exec bit, the working tree should agree.
    if os.name == "posix":
        assert SCRIPT.stat().st_mode & stat.S_IXUSR, (
            "committed 100755 but not executable in the working tree")


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


def test_dependencies_are_hash_pinned_not_installed_by_name():
    """Scorecard #317/#318/#319: bare `pip install` is a supply-chain hole.

    Three medium alerts fired on this script for `pip install aiohttp`
    and `pip install psutil`. Unpinned is bad anywhere; here the
    artifact lands on the operator's phone and is imported by a bridge
    holding shell access on a device that roams between untrusted
    networks. A typosquat arrives with execution rights.
    """
    text = _text()
    assert "--require-hashes" in text, (
        "the installer no longer verifies dependency hashes")
    assert "requirements-termux.txt" in text

    offenders = [
        line.strip() for line in text.splitlines()
        if "pip install" in line
        and "--require-hashes" not in line
        and not line.strip().startswith("#")
    ]
    assert not offenders, (
        "these pip invocations install by name without hash verification, "
        "which is what Scorecard flagged:\n  " + "\n  ".join(offenders))


def test_a_hash_mismatch_is_never_worked_around():
    """The failure path must not teach the operator to disable the check.

    A `die` message suggesting `--no-deps` would undo the fix the moment
    a pin goes stale. It must point at refreshing pins on a trusted
    machine instead.
    """
    text = _text()
    assert "HASH MISMATCH" in text, (
        "the installer does not explain what a hash failure means")
    assert "refresh_termux_requirements.py" in text, (
        "no recovery path offered for stale pins")
    for escape in ("--no-deps", "--trusted-host", "--index-url",
                   "PIP_NO_VERIFY", "--break-system-packages"):
        assert escape not in text, (
            f"installer offers {escape} as a workaround; a documented "
            f"bypass is the same as no check")


def test_psutil_stays_optional_at_runtime():
    """Pinned does not mean mandatory.

    Every psutil import in the bridge is lazy and guarded and the bridge
    degrades honestly without it -- measured. If a future edit makes a
    missing psutil fatal, Termux installs start failing on devices where
    it will not build.
    """
    text = _text()
    lines = text.splitlines()
    checks = [i for i, ln in enumerate(lines) if "import psutil" in ln]
    assert checks, "the installer no longer reports psutil status"
    block = lines[checks[0]:checks[0] + 6]
    assert not any("die " in ln for ln in block), (
        "a missing psutil now aborts the install; it must degrade:\n"
        + "\n".join(block))

    # aiohttp, by contrast, must stay fatal: a "successful" install that
    # cannot serve is worse than a failed one.
    assert any("dependency install failed" in ln for ln in lines), (
        "a failed dependency install no longer aborts")


def test_the_pinned_requirements_file_is_well_formed():
    """A pin file pip cannot parse is a pin file that never runs.

    Structure, not versions: versions move, the shape must not. Every
    requirement needs at least one sha256, because `--require-hashes`
    rejects the entire file over a single entry without digests -- and
    the operator would meet that failure on the phone.
    """
    import re

    pins = ROOT / "scripts" / "requirements-termux.txt"
    assert pins.is_file(), "the pinned requirements file is missing"

    body = [ln.rstrip() for ln in pins.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    assert body, "the pin file contains no requirements"

    requirement = re.compile(r"^[A-Za-z0-9._-]+==[A-Za-z0-9.+!-]+ \\$")
    digest = re.compile(r"^ {4}--hash=sha256:[0-9a-f]{64}( \\)?$")

    packages = 0
    hashes_for_current = 0
    for line in body:
        if requirement.match(line):
            if packages:
                assert hashes_for_current, "a requirement carried no hashes"
            packages += 1
            hashes_for_current = 0
        elif digest.match(line):
            hashes_for_current += 1
        else:
            raise AssertionError(f"unparseable line in pin file: {line!r}")
    assert hashes_for_current, "the last requirement carried no hashes"

    assert any(ln.startswith("aiohttp==") for ln in body), "aiohttp is not pinned"
    assert packages >= 5, (
        f"only {packages} packages pinned; transitive dependencies are "
        f"missing and --require-hashes will reject the install")


def _bash_actually_runs() -> bool:
    """True only when `bash` on PATH is a working shell.

    v4.167.3: `shutil.which("bash")` is not the same question. On
    `windows-latest` GitHub ships `C:\\Windows\\System32\\bash.exe`, the
    **WSL launcher stub** -- `which` finds it, and every invocation
    prints "Windows Subsystem for Linux has no installed distributions."
    to *stdout* and exits 1. So `bash -n script.sh` returned 1 with an
    empty stderr and the assertion failed with a blank message on all
    five Windows jobs, which is exactly how it read in the CI log.

    Reproduced locally by stubbing a bash that exits 1 with an empty
    stderr; the signature matched the CI failure exactly.

    Asking "does bash work" instead of "does bash exist" is the fix.
    Anything that cannot parse a trivial script is not a shell this test
    can use.
    """
    if shutil.which("bash") is None:
        return False
    try:
        probe = subprocess.run(["bash", "-c", "exit 0"],
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


@pytest.mark.skipif(not _bash_actually_runs(),
                    reason="no working bash (a WSL stub on PATH is not a shell)")
def test_the_script_is_syntactically_valid():
    result = subprocess.run(["bash", "-n", str(SCRIPT)],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"bash -n failed rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}")


def test_the_installer_has_no_carriage_returns():
    """CRLF would break the script on the phone, and git may introduce it.

    There is no `.gitattributes` in this repo, so a Windows clone with
    the default `core.autocrlf=true` checks `.sh` files out with CRLF.
    Bash then fails on `for arg in "$@"; do\\r` -- verified locally: the
    LF copy parses clean, the CRLF copy dies with
    `syntax error near unexpected token $'do\\r'`.

    The installer is fetched onto the phone, so this must be pinned in
    the file itself rather than trusted to checkout settings.
    """
    raw = SCRIPT.read_bytes()
    assert b"\r\n" not in raw, (
        "install_termux.sh contains CRLF line endings; bash on the phone "
        "will fail with `syntax error near unexpected token $'do\\r'`")


@pytest.mark.skipif(
    not _bash_actually_runs() or not sys.platform.startswith("linux"),
    reason="needs a POSIX shell on a Linux host: the installer's own "
           "self-check refuses to call a Darwin or Windows machine Android, "
           "which is correct behaviour and not something to stub out")
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
    # The release ships the pinned requirements file and the installer
    # refuses to run without it, so the simulated tree must have it too.
    (bridge_dir / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "requirements-termux.txt",
                 bridge_dir / "scripts" / "requirements-termux.txt")

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


@pytest.mark.skipif(
    not _bash_actually_runs() or not sys.platform.startswith("linux"),
    reason="needs a POSIX shell on a Linux host")
def test_it_refuses_a_non_termux_host(tmp_path):
    """Reverse sabotage: running this on a desktop must abort, not proceed."""
    env = dict(os.environ)
    env.pop("PREFIX", None)
    env.pop("ANDROID_ROOT", None)
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True,
                            text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert result.returncode != 0, "installer ran happily on a non-phone"
    assert "Termux" in result.stderr or "Termux" in result.stdout
