"""v4.169.25 -- CI installed packages without hash pinning.

Scorecard reported `pipCommand not pinned by hash` (medium, score 7) on
`.github/workflows/ci.yml`. It named one line; there were eight, across
both workflows:

  * `pip install pytest` and `pip install hypothesis` in the contract job
  * `pip install -r requirements.txt` in six jobs -- that file carries
    floors (`aiohttp>=3.14.1`), not pins
  * `pip install "bandit>=1.7"`, `"semgrep>=1.170"`, `"pip-audit>=2.7"`
    in the security scan

The last three are the worst of it: a security scan that resolves its
own scanner from an unpinned range is deciding what counts as secure
using code nobody reviewed, and its verdict gates every release.

Every package in the first two groups was already hash-pinned in
`requirements-ci.lock`. The scanners now have their own
`requirements-security.lock`, generated the same way as the existing
lint lock.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RATCHET = REPO_ROOT / "scripts" / "pinned_pip_ratchet.py"


def _run_ratchet() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(RATCHET)],
                          capture_output=True, text=True, timeout=300)


def test_no_workflow_installs_without_hashes() -> None:
    proc = _run_ratchet()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_security_lock_covers_all_three_scanners() -> None:
    """The scanners whose verdict gates a release must be pinned."""
    lock = (REPO_ROOT / "requirements-security.lock").read_text(encoding="utf-8")
    for scanner in ("bandit", "semgrep", "pip-audit"):
        assert re.search(rf"^{re.escape(scanner)}==", lock, re.M), (
            f"{scanner} is not pinned in requirements-security.lock"
        )
    assert lock.count("--hash=sha256:") > 100, "a lock with no hashes is not a lock"


def test_security_workflow_uses_the_lock() -> None:
    body = (WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert "requirements-security.lock" in code
    for floor in ('"bandit>=', '"semgrep>=', '"pip-audit>='):
        assert floor not in code, f"unpinned scanner install is back: {floor}"


def test_ratchet_catches_a_plain_unpinned_install(tmp_path: Path) -> None:
    probe = WORKFLOWS / "_pinned_pip_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pip install requests\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "_pinned_pip_probe.yml" in proc.stdout


def test_the_sfw_exemption_is_not_a_hole(tmp_path: Path) -> None:
    """Sabotage found this: a prefix match let anything through.

    The Socket Firewall step deliberately attempts an unpinned resolve to
    prove the firewall blocks it. The first cut exempted any line
    starting with `sfw `, so `sfw pip install evil-package` from any
    workflow was invisible. The exemption is now the exact command in
    the one step that needs it.
    """
    probe = WORKFLOWS / "_sfw_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: sneaky\n        run: |\n"
        "          sfw pip install evil-package\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1, "an arbitrary package hid behind the sfw prefix"
    assert "_sfw_probe.yml" in proc.stdout


def test_legitimate_forms_are_not_flagged() -> None:
    """Reverse sabotage: bootstrapping pip and installing our own wheel."""
    probe = WORKFLOWS / "_pinned_ok_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python -m pip install --upgrade pip\n"
        "      - run: python -m pip install --require-hashes -r requirements-ci.lock\n"
        "      - run: python -m pip install --no-deps --no-build-isolation -e .\n"
        "      - run: python -m pip install --no-deps dist/arena.whl\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout


def test_ratchet_refuses_a_truncated_scan() -> None:
    """A gate that scans nothing reports OK forever."""
    source = RATCHET.read_text(encoding="utf-8")
    assert "MIN_FILES_SCANNED" in source
    probe = REPO_ROOT / "scripts" / "_pinned_pip_probe_ratchet.py"
    probe.write_text(source.replace('WORKFLOWS.glob("*.y*ml")',
                                    'WORKFLOWS.glob("nothing-*.yml")'),
                     encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(probe)],
                              capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "scanned only" in proc.stdout


def test_ratchet_is_wired_into_preflight() -> None:
    source = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "pinned_pip_ratchet.py" in source


# --- the other alert in the same batch: plaintext LAN URLs ---------------

def test_lan_urls_carry_a_plaintext_warning() -> None:
    """devskim DS137138 was right about the fact, not the fix.

    The bridge has no TLS listener, so `http://` is the scheme that
    works -- rewriting it to `https://` would produce a URL that
    connects to nothing. What was missing is that these URLs carry the
    bearer token, and on a LAN or a shared tailnet anything on the path
    can read it. A reader who sees a URL and no warning reasonably
    assumes someone checked.
    """
    from arena.mobile.access_info import describe

    wide = describe(bind="0.0.0.0", port=8765, tunnels={})
    if wide["lan_urls"]:
        assert wide["lan_urls_are_plaintext"] is True
        assert "clear text" in wide["transport_warning"]
        assert "TLS" in wide["transport_warning"]


def test_loopback_bind_has_no_plaintext_warning() -> None:
    """Nothing is exposed, so there is nothing to warn about.

    A warning that fires when it does not apply is noise, and noise is
    how a real one gets ignored.
    """
    from arena.mobile.access_info import describe

    info = describe(bind="127.0.0.1", port=8765, tunnels={})
    assert info["lan_urls"] == []
    assert info["lan_urls_are_plaintext"] is False
    assert "transport_warning" not in info


def test_the_urls_stay_http_because_that_is_what_works() -> None:
    """Reverse check: do not 'fix' the scanner finding by lying.

    An https:// URL here would be a URL that connects to nothing, which
    is worse than a plain one with a warning next to it.
    """
    from arena.mobile import access_info

    source = Path(access_info.__file__ or "").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines()
                     if not ln.strip().startswith("#"))
    assert 'f"http://{a[' in code, "the LAN URL scheme was changed"
    assert "https://{a[" not in code, (
        "the bridge has no TLS listener; an https URL would not connect"
    )
