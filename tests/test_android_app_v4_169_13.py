"""v4.169.13 -- the Android app, and the two sandbox facts it must respect.

Termux was never a good answer. Installing through it is awkward, and
HyperOS reaps the process regardless of `termux-wake-lock`: a partial
wake lock keeps the CPU awake, it does not exempt an app from Xiaomi's
background policy. Only an app with a foreground service can hold that
exemption, and only the user can grant it.

The first design of this app was wrong in a way worth keeping written
down, because the device proved it in one screenshot:

  * It planned to launch the bridge with `ProcessBuilder` on
    `/data/data/com.termux/files/usr/bin/python3`. Android's per-app
    sandbox forbids executing -- or even `stat`-ing -- another app's
    files. Every existence check returned false, and the UI reported
    "Termux installed: no" on a phone running Termux.
  * The device also has the Google Play build of Termux
    (`versionName=googleplay.2026.06.21`), which ships without
    RUN_COMMAND, so the documented IPC route is absent too.

What does cross the boundary, verified from a different UID on the
device: a TCP connection to loopback. `GET /v1/version` on
127.0.0.1:8765 answered 200. So the app supervises over HTTP and asks
the *package manager* -- not the filesystem -- whether Termux exists.

These tests read the sources. They cannot run an APK, but they can stop
the two impossible approaches from creeping back in, which is the part
that cost a build round trip each time.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android_app"
SRC = APP / "src" / "ai" / "arena" / "bridge"
MANIFEST = APP / "AndroidManifest.xml"


def _java(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_the_app_sources_exist() -> None:
    for name in ("BridgeService.java", "BridgePaths.java",
                 "BridgeProbe.java", "BootReceiver.java", "MainActivity.java"):
        assert (SRC / name).is_file(), f"{name} is missing"


def test_no_source_tries_to_execute_a_termux_binary() -> None:
    """The sandbox makes this impossible; it must not come back."""
    for path in sorted(SRC.glob("*.java")):
        text = path.read_text(encoding="utf-8")
        # Comments explain the history, so only look at code lines.
        code = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith(("*", "//", "/*"))
        )
        assert "ProcessBuilder" not in code, (
            f"{path.name}: ProcessBuilder cannot run Termux's python -- "
            f"different UID, different sandbox"
        )
        assert "Runtime.getRuntime().exec" not in code, f"{path.name}: same problem"


def test_termux_presence_is_asked_of_the_package_manager() -> None:
    """A File check answers 'no' for a package that is installed."""
    main = _java("MainActivity.java")
    assert "getPackageManager().getPackageInfo" in main
    code = "\n".join(
        line for line in main.splitlines()
        if not line.strip().startswith(("*", "//", "/*"))
    )
    assert "/data/data/com.termux" not in code, (
        "the UI must not stat another app's data directory; that is what "
        "made it report 'Termux installed: no' on a phone running Termux"
    )


def test_manifest_declares_the_package_query() -> None:
    """Android 11+ hides other packages unless they are declared.

    Without this the getPackageInfo above throws NameNotFoundException
    and the honest lookup produces the same wrong answer as the file
    check did. Found on the device, after fixing the file check.
    """
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert "<queries>" in manifest
    assert 'android:name="com.termux"' in manifest
    # Strip XML comments first. Three releases in a row a gate flagged
    # its own explanatory prose (psutil, download&, control_status);
    # this file names QUERY_ALL_PACKAGES in a comment precisely to say
    # it is not used.
    import re as _re
    code = _re.sub(r"<!--.*?-->", "", manifest, flags=_re.S)
    assert "QUERY_ALL_PACKAGES" not in code, (
        "declare the one package we integrate with, not a blanket query"
    )


def test_manifest_has_what_hyperos_needs() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    for permission in (
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.WAKE_LOCK",
    ):
        assert permission in manifest, f"missing {permission}"
    # API 34 requires a declared type; specialUse is the honest one for a
    # long-running local server the device owner started.
    assert 'android:foregroundServiceType="specialUse"' in manifest


def test_boot_receiver_replaces_termux_boot() -> None:
    """Termux:Boot needed a second app installed by hand from F-Droid."""
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert "android.intent.action.BOOT_COMPLETED" in manifest
    assert ".BootReceiver" in manifest
    assert "startForegroundService" in _java("BootReceiver.java")


def test_status_comes_from_the_port_not_from_a_flag() -> None:
    """v4.169.5 shipped a bridge that told a halted agent it was running.

    The notification is the only thing visible when the phone is in a
    pocket, so it must never say 'serving' on the strength of having
    been started once.
    """
    service = _java("BridgeService.java")
    assert "BridgeProbe.version()" in service or "BridgeProbe.portOpen" in service
    probe = _java("BridgeProbe.java")
    assert "127.0.0.1" in probe
    assert "/v1/version" in probe or "versionUrl" in probe


def test_probe_json_reader_survives_junk() -> None:
    """The status screen must not crash on an unexpected body."""
    probe = _java("BridgeProbe.java")
    body = probe[probe.index("static String extract("):]
    for guard in ("< 0", "return null"):
        assert guard in body
    assert "throw" not in body


def test_build_script_checks_the_jdk_version() -> None:
    """JDK 11 fails inside aapt2 with a class-version error that reads
    like a corrupt SDK. Cost a confused detour; checked up front now."""
    script = (REPO_ROOT / "scripts" / "build_android_apk.sh").read_text(encoding="utf-8")
    assert "JDK 17" in script
    assert "-ge 17" in script
    # And it must verify what it produced rather than trust the signer.
    assert "apksigner verify" in script


def test_app_version_matches_the_bridge() -> None:
    """A phone showing a stale app version next to a fresh bridge is the
    kind of mismatch that wastes an hour of debugging."""
    from arena.constants import VERSION

    manifest = MANIFEST.read_text(encoding="utf-8")
    match = re.search(r'android:versionName="([^"]+)"', manifest)
    assert match, "versionName missing from the manifest"
    assert match.group(1) == VERSION, (
        f"manifest says {match.group(1)}, arena/constants.py says {VERSION}"
    )


# --- the release builder packs the working tree, not the commit ------------

def test_release_zip_refuses_untracked_files(tmp_path: Path) -> None:
    """v4.169.12 was built from a tree holding the unfinished app.

    1142 files instead of 1105: java sources and a keystore, inside an
    archive labelled with a tag that contained none of them. Nobody was
    warned, because the builder walks the filesystem rather than the
    commit. The archive was discarded and rebuilt from a clean clone,
    and the builder now refuses instead of shipping it.
    """
    import subprocess
    import sys as _sys

    probe = REPO_ROOT / "_release_untracked_probe.txt"
    probe.write_text("stray\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [_sys.executable, str(REPO_ROOT / "scripts" / "make_release_zip.py"),
             "9.9.9", str(tmp_path / "out.zip")],
            capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "_release_untracked_probe.txt" in proc.stderr
    assert not (tmp_path / "out.zip").exists(), "it must not write the archive"


def test_release_zip_can_be_overridden_deliberately(tmp_path: Path) -> None:
    """An escape hatch, so the gate cannot block a legitimate build."""
    import subprocess
    import sys as _sys

    probe = REPO_ROOT / "_release_untracked_probe2.txt"
    probe.write_text("stray\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [_sys.executable, str(REPO_ROOT / "scripts" / "make_release_zip.py"),
             "9.9.9", str(tmp_path / "out.zip"), "--allow-untracked"],
            capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "out.zip").exists()


# --- v4.169.19: the boot script started a second copy and died ------------

def test_boot_script_refuses_to_start_a_second_copy() -> None:
    """A dead bridge that looks started is worse than one that admits it.

    After an in-place update the old process still held 8765. The boot
    script exec'd anyway and aiohttp raised
    `[errno 98] address already in use` into a log nobody reads, leaving
    a phone that reported "started" and served nothing. Reproduced on the
    device before fixing.
    """
    script = (REPO_ROOT / "scripts" / "bootstrap_android.sh").read_text(encoding="utf-8")
    start = script.index('cat > "$BOOT_DIR/arena-bridge.sh"')
    heredoc = script[start:script.index("BOOTEOF", start + 40)]
    assert "connect_ex" in heredoc, (
        "the boot script must check the port before exec'ing the bridge"
    )
    assert "already serving" in heredoc
    # The check has to come before the exec, or it proves nothing.
    assert heredoc.index("connect_ex") < heredoc.index("exec python3")


def test_boot_script_port_check_behaves_both_ways(tmp_path: Path) -> None:
    """Run the guard's logic rather than trusting the shell text.

    The Android boot script is `sh`, and Windows runners have no `sh` --
    the first cut of this test shelled out and every windows-latest job
    went red while three Linux ones passed. Third time this exact shape
    has bitten (v4.169.9, v4.169.15, now this), so the shell is gone:
    the check is one `connect_ex` call, and that is what gets exercised.
    """
    import socket

    port = 18771

    def guard_says_already_serving() -> bool:
        """Exactly what the boot script's python -c evaluates."""
        probe = socket.socket()
        try:
            return probe.connect_ex(("127.0.0.1", port)) == 0
        finally:
            probe.close()

    assert guard_says_already_serving() is False, "nothing should be listening yet"

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    try:
        assert guard_says_already_serving() is True
    finally:
        srv.close()

    # And the script must act on that answer by exiting 0, not by
    # starting a second copy: an already-running bridge is success.
    script = (REPO_ROOT / "scripts" / "bootstrap_android.sh").read_text(encoding="utf-8")
    start_at = script.index('cat > "$BOOT_DIR/arena-bridge.sh"')
    heredoc = script[start_at:script.index("BOOTEOF", start_at + 40)]
    guard = heredoc[heredoc.index("connect_ex"):heredoc.index("termux-wake-lock")]
    assert "exit 0" in guard, guard


def test_bootstrap_points_at_the_apk_for_autostart() -> None:
    """Termux:Boot needed a second F-Droid app installed by hand."""
    script = (REPO_ROOT / "scripts" / "bootstrap_android.sh").read_text(encoding="utf-8")
    assert "ai.arena.bridge" in script
    assert "arena-bridge.apk" in script


def test_posix_shell_ratchet_is_wired_and_catches_a_bare_shell(tmp_path: Path) -> None:
    """The gate for the class, not just this instance."""
    import subprocess
    import sys as _sys

    assert "posix_shell_test_ratchet.py" in (
        REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")

    probe = REPO_ROOT / "tests" / "test_zz_posix_shell_probe.py"
    probe.write_text(
        "import subprocess\n\n\ndef test_bad():\n"
        '    subprocess.run(["sh", "-c", "echo hi"])\n',
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [_sys.executable, str(REPO_ROOT / "scripts" / "posix_shell_test_ratchet.py")],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "test_zz_posix_shell_probe.py" in proc.stdout
