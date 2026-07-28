"""v4.104.0 -- Windows AppContainer runner script guardrails.

These are static tests because CI cannot safely launch Windows AppContainers in
all runners, but they pin the security-critical shape of the script so a future
refactor cannot silently regress to the old "launch only, no grants/capture"
version.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "appcontainer_run.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_appcontainer_script_grants_scratch_and_runtime_acl():
    s = _script()
    assert "EnsureProfileSidString" in s
    assert "FileSystemAccessRule" in s
    assert "ConvertSidToStringSidW" in s
    assert "SecurityIdentifier($sidString)" in s
    assert "Grant-AppContainerPath $ScratchDir ([System.Security.AccessControl.FileSystemRights]::Modify)" in s
    assert "Grant-AppContainerPath $RuntimeGrantDir ([System.Security.AccessControl.FileSystemRights]::ReadAndExecute)" in s
    assert "Fail-Closed" in s


def test_appcontainer_script_captures_stdout_stderr_with_inheritable_handles():
    s = _script()
    assert "STARTF_USESTDHANDLES" in s
    assert "hStdOutput" in s and "hStdError" in s
    assert "CreateFile(stdout)" in s and "CreateFile(stderr)" in s
    assert "[Console]::Out.Write" in s
    assert "[Console]::Error.Write" in s


def test_appcontainer_script_uses_no_capabilities_and_timeout_kill():
    s = _script()
    assert "CapabilityCount = 0" in s
    assert "no internetClient" in s
    assert "WaitForSingleObject" in s
    assert "TerminateProcess" in s
    assert "124" in s
