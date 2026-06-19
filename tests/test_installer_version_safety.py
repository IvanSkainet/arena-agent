#!/usr/bin/env python3
"""Write tests/test_installer_version_safety.py — guardrails for the installer fix.

Tests (no network, no actual install):
1. _arena_version_lt() correctly compares semver-ish strings
2. install.sh defaults BRANCH to master (not v3-modular-core)
3. install.sh never uses `git checkout -B` (the destructive pattern we removed)
4. install.sh uses `git merge --ff-only` for updates (non-destructive)
5. install.bat includes the soft version-check (queries GitHub API, no auto-update)
"""
from pathlib import Path
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"
INSTALL_BAT = ROOT / "install.bat"


def _has_bash() -> bool:
    return shutil.which("bash") is not None


def _extract_function(src: str, name: str) -> str:
    """Extract a bash function body from source text."""
    lines = src.split("\n")
    out = []
    in_fn = False
    brace_depth = 0
    for line in lines:
        if not in_fn:
            if line.startswith(f"{name}()"):
                in_fn = True
                brace_depth = 0
                out.append(line)
                if "{" in line:
                    brace_depth += line.count("{") - line.count("}")
                continue
        else:
            out.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0 and "{" in "\n".join(out):
                break
    return "\n".join(out)


def test_install_sh_defaults_to_master_branch():
    """Default BRANCH must be `master`, not the stale `v3-modular-core`."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    # The default assignment line, allowing leading comment lines above it
    assert 'BRANCH="${ARENA_BRANCH:-master}"' in src, (
        "install.sh should default BRANCH to master so fresh installs get the "
        "current stable release instead of the lagging v3-modular-core branch."
    )
    assert 'BRANCH="${ARENA_BRANCH:-v3-modular-core}"' not in src, (
        "install.sh must NOT default to v3-modular-core anymore."
    )


def test_install_sh_does_not_force_checkout_branch():
    """The destructive `git checkout -B <branch> FETCH_HEAD` must be gone.

    That pattern silently switched branches on existing installations and
    downgraded users who had pinned themselves to a release branch.
    """
    src = INSTALL_SH.read_text(encoding="utf-8")
    assert "git checkout -B" not in src, (
        "install.sh must not use `git checkout -B` - it silently switches "
        "branches and discards the user's chosen branch on update."
    )


def test_install_sh_uses_fast_forward_only_merge():
    """Updates must use `git merge --ff-only`, never `git reset --hard`."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    assert 'git merge --ff-only' in src, (
        "install.sh should use `git merge --ff-only` for updates so local "
        "commits are never silently discarded."
    )
    # The update block must NOT contain a destructive reset --hard
    # (the only allowed reset --hard is in a user-facing hint string, which
    # we tolerate; the actual update logic must use ff-only merge)
    assert "git reset --hard origin/" not in src.replace(
        'git reset --hard origin/$CURRENT_BRANCH"', "HINT_STRING"
    ).replace(
        "git reset --hard origin/\\\"$CURRENT_BRANCH\\\"", "HINT_STRING"
    ), (
        "install.sh must not auto-run `git reset --hard origin/...` - that "
        "would discard local work. Allowed only inside an info/hint string."
    )


def test_install_sh_has_version_comparison_helper():
    """The _arena_version_lt() helper must exist for semver comparison."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    assert "_arena_version_lt()" in src, (
        "install.sh should define _arena_version_lt() for version-aware "
        "update decisions."
    )


VERSION_TEST_CASES = [
    # (v1, v2, expected_v1_lt_v2)
    ("3.1.5", "3.1.5", False),    # equal
    ("3.1.4", "3.1.5", True),     # older patch
    ("3.1.5", "3.1.4", False),    # newer patch
    ("3.1.0", "3.1.5", True),     # much older patch
    ("3.2.0", "3.1.5", False),    # newer minor
    ("3.0.0", "3.1.5", True),     # older minor
    ("4.0.0", "3.1.5", False),    # newer major
    ("v3.1.5", "3.1.5", False),   # v-prefix normalization
    ("3.1.5", "v3.1.5", False),
    ("3.1", "3.1.5", True),       # shorter version padded with zeros
    ("3.1.10", "3.1.9", False),   # double-digit patch
    ("3.1.5-rc1", "3.1.5", False),# pre-release suffix stripped (treated as 3.1.5)
]


def test_arena_version_lt_semver():
    """_arena_version_lt must correctly compare X.Y.Z versions."""
    if not _has_bash():
        sys.stderr.write("\n[skip] bash not available, cannot test _arena_version_lt\n")
        return
    src = INSTALL_SH.read_text(encoding="utf-8")
    fn_body = _extract_function(src, "_arena_version_lt")
    assert fn_body, "Could not extract _arena_version_lt() from install.sh"

    # Build a tiny bash test script
    test_script = f"""#!/usr/bin/env bash
{fn_body}

for tc in '{"' '".join(f"{v1}:{v2}:{'true' if exp else 'false'}" for v1,v2,exp in VERSION_TEST_CASES)}'; do
    v1="${{tc%%:*}}"
    rest="${{tc#*:}}"
    v2="${{rest%%:*}}"
    exp="${{rest##*:}}"
    _arena_version_lt "$v1" "$v2"
    rc=$?
    [ $rc -eq 0 ] && act=true || act=false
    if [ "$act" != "$exp" ]; then
        echo "FAIL: $v1 < $v2 => $act (expected $exp)"
        exit 1
    fi
done
echo "ALL_PASS"
"""
    result = subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"_arena_version_lt test failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ALL_PASS" in result.stdout, (
        f"Expected ALL_PASS in output, got: {result.stdout}"
    )


def test_install_bat_has_soft_version_check():
    """install.bat must include the soft version-check that informs (not auto-updates)."""
    if not INSTALL_BAT.exists():
        sys.stderr.write("\n[skip] install.bat not present on this platform\n")
        return
    src = INSTALL_BAT.read_text(encoding="utf-8")
    # Must query the GitHub releases API
    assert "api.github.com/repos/IvanSkainet/arena-agent/releases/latest" in src, (
        "install.bat should query GitHub API for the latest release to inform "
        "the user when an update is available."
    )
    # Must NOT do git pull on the bridge itself (only on skills/superpowers)
    # Look for `git pull` NOT preceded by `skills/superpowers`
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if "git" in line and "pull" in line:
            # The git pull must be inside the superpowers block, not for the bridge
            # We allow: git -C "%BRIDGE_DIR%\skills\superpowers" pull
            # We forbid: git pull (bare, would update bridge)
            stripped = line.strip()
            if stripped.startswith("git pull") or stripped.startswith('git -C "%BRIDGE_DIR%" pull'):
                # Check it's about superpowers
                assert "superpowers" in stripped, (
                    f"install.bat line {i+1} does git pull on bridge itself "
                    f"(forbidden - should only update skills):\n  {line}"
                )


def test_install_bat_does_not_force_checkout():
    """install.bat must not do git checkout for the bridge (only for skills)."""
    if not INSTALL_BAT.exists():
        return
    src = INSTALL_BAT.read_text(encoding="utf-8")
    # No bare `git checkout` for the bridge directory
    lines = src.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("git checkout"):
            # Only allowed if scoped to skills/superpowers via -C
            assert "-C" in stripped and "superpowers" in stripped, (
                f"install.bat line {i+1} does git checkout without scoping to skills:\n  {line}"
            )


def test_install_sh_exports_desktop_session_metadata_when_available():
    src = INSTALL_SH.read_text(encoding="utf-8")
    assert 'Environment=XDG_SESSION_TYPE=${XDG_SESSION_TYPE}' in src
    assert 'Environment=XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP}' in src
    assert 'Environment=DESKTOP_SESSION=${DESKTOP_SESSION}' in src
