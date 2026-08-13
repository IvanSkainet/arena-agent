"""Release artifact verification binds identity, layout, and canonical bytes."""
from __future__ import annotations

import importlib.util
import json
import stat
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_release_zip.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_release_zip", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _module()


def _entries(version: str = "9.9.9") -> dict[str, bytes]:
    entries = {name: b"placeholder\n" for name in M.REQUIRED}
    entries[f"{M.PREFIX}arena/constants.py"] = f'VERSION = "{version}"\n'.encode()
    entries[f"{M.PREFIX}pyproject.toml"] = (
        f'[project]\nname = "arena-agent"\nversion = "{version}"\n'
    ).encode()
    return entries


def _write_zip(
    path: Path,
    *,
    version: str = "9.9.9",
    extra: dict[str, bytes] | None = None,
    timestamp_path: str | None = None,
    symlink_path: str | None = None,
) -> None:
    entries = _entries(version)
    entries.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(entries.items()):
            timestamp = (2026, 1, 2, 3, 4, 6) if name == timestamp_path else M.ZIP_TIMESTAMP
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.create_system = 3
            mode = stat.S_IFLNK | 0o777 if name == symlink_path else stat.S_IFREG | 0o644
            info.external_attr = mode << 16
            archive.writestr(info, body, compress_type=zipfile.ZIP_DEFLATED)


def test_valid_identical_pair_writes_machine_readable_evidence(tmp_path: Path) -> None:
    versioned = tmp_path / "arena-agent-v9.9.9.zip"
    alias = tmp_path / "arena-agent.zip"
    report = tmp_path / "verification.json"
    _write_zip(versioned)
    alias.write_bytes(versioned.read_bytes())

    assert M.main([
        "--versioned", str(versioned),
        "--alias", str(alias),
        "--expected-version", "9.9.9",
        "--json-out", str(report),
    ]) == 0
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["ok"] is True
    assert evidence["version"] == "9.9.9"
    assert evidence["sha256"] == evidence["aliasSha256"]
    assert evidence["files"] == len(M.REQUIRED)


def test_alias_must_be_the_exact_same_bytes(tmp_path: Path) -> None:
    versioned = tmp_path / "arena-agent-v9.9.9.zip"
    alias = tmp_path / "arena-agent.zip"
    _write_zip(versioned)
    _write_zip(alias, extra={f"{M.PREFIX}extra.txt": b"different\n"})
    with pytest.raises(M.VerificationError, match="not byte-identical"):
        M.verify_pair(versioned, alias, expected_version="9.9.9")


def test_forbidden_development_path_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "bad.zip"
    _write_zip(artifact, extra={f"{M.PREFIX}tests/test_secret.py": b"bad\n"})
    with pytest.raises(M.VerificationError, match="forbidden development path"):
        M.verify_zip(artifact, expected_version="9.9.9")


def test_source_versions_must_match_candidate_version(tmp_path: Path) -> None:
    artifact = tmp_path / "bad-version.zip"
    _write_zip(artifact, version="9.9.8")
    with pytest.raises(M.VerificationError, match="version mismatch"):
        M.verify_zip(artifact, expected_version="9.9.9")


def test_noncanonical_timestamp_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "bad-time.zip"
    target = f"{M.PREFIX}README.md"
    _write_zip(artifact, timestamp_path=target)
    with pytest.raises(M.VerificationError, match="non-canonical timestamp"):
        M.verify_zip(artifact, expected_version="9.9.9")


def test_symlink_entry_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "bad-link.zip"
    target = f"{M.PREFIX}README.md"
    _write_zip(artifact, symlink_path=target)
    with pytest.raises(M.VerificationError, match="non-regular"):
        M.verify_zip(artifact, expected_version="9.9.9")
