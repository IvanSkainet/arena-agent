#!/usr/bin/env python3
"""Fail-closed structural and identity verification for release ZIP bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

PREFIX = "arena-bridge/"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
RELEASE_PROVENANCE = f"{PREFIX}.arena-release-provenance.json"
REQUIRED = frozenset({
    RELEASE_PROVENANCE,
    f"{PREFIX}unified_bridge.py",
    f"{PREFIX}_arena_helper.py",
    f"{PREFIX}arena/constants.py",
    f"{PREFIX}pyproject.toml",
    f"{PREFIX}scripts/make_release_zip.py",
    f"{PREFIX}install.sh",
    f"{PREFIX}install.bat",
    f"{PREFIX}README.md",
    f"{PREFIX}LICENSE",
})
FORBIDDEN_PREFIXES = (
    f"{PREFIX}tests/",
    f"{PREFIX}.github/",
    f"{PREFIX}.git/",
    f"{PREFIX}dev/",
)
FORBIDDEN_BASENAMES = frozenset({
    "token.txt",
    "audit.jsonl",
    "requests.jsonl",
    "bridge.log",
    "coverage.xml",
    ".coverage",
    "version.json",
})
_SOURCE_VERSION_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_STRICT_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class VerificationError(ValueError):
    """The candidate bytes do not satisfy the release artifact contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_version(archive: zipfile.ZipFile) -> tuple[str, str]:
    constants = archive.read(f"{PREFIX}arena/constants.py").decode("utf-8")
    match = _SOURCE_VERSION_RE.search(constants)
    if not match:
        raise VerificationError("arena/constants.py has no literal VERSION")
    constants_version = match.group(1)
    pyproject = archive.read(f"{PREFIX}pyproject.toml").decode("utf-8")
    in_project = False
    project_version = ""
    for line in pyproject.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("[") and stripped.endswith("]"):
            break
        if in_project:
            version_match = re.fullmatch(r'version\s*=\s*"([^"]+)"', stripped)
            if version_match:
                project_version = version_match.group(1)
                break
    if not project_version:
        raise VerificationError("cannot read [project].version")
    return constants_version, project_version


def _archive_provenance(archive: zipfile.ZipFile, *, expected_version: str,
                        expected_source_commit: str | None,
                        expected_candidate_run: str | None) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(RELEASE_PROVENANCE).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise VerificationError(f"invalid release provenance: {exc}") from exc
    required = {"schemaVersion", "repository", "sourceCommit", "releaseTag", "candidateRunId"}
    if not isinstance(value, dict) or set(value) != required:
        raise VerificationError("release provenance keys do not match the contract")
    if value["schemaVersion"] != 1 or isinstance(value["schemaVersion"], bool):
        raise VerificationError("unsupported release provenance schemaVersion")
    if value["repository"] != "IvanSkainet/arena-agent":
        raise VerificationError("unexpected release provenance repository")
    source = value["sourceCommit"]
    run_id = value["candidateRunId"]
    if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise VerificationError("release provenance sourceCommit is malformed")
    if value["releaseTag"] != f"v{expected_version}":
        raise VerificationError("release provenance tag does not match expected version")
    if not isinstance(run_id, str) or (run_id != "local" and re.fullmatch(r"[1-9][0-9]*", run_id) is None):
        raise VerificationError("release provenance candidateRunId is malformed")
    if expected_source_commit is not None and source != expected_source_commit:
        raise VerificationError("release provenance sourceCommit does not match workflow SHA")
    if expected_candidate_run is not None and run_id != expected_candidate_run:
        raise VerificationError("release provenance candidateRunId does not match workflow run")
    return value


def verify_zip(path: Path, *, expected_version: str,
               expected_source_commit: str | None = None,
               expected_candidate_run: str | None = None) -> dict[str, Any]:
    if _STRICT_VERSION_RE.fullmatch(expected_version) is None:
        raise VerificationError("expected version must be strict X.Y.Z")
    if not path.is_file():
        raise VerificationError(f"artifact does not exist: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise VerificationError(f"CRC failure in {bad}")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not names:
                raise VerificationError("archive is empty")
            if len(names) != len(set(names)):
                raise VerificationError("archive contains duplicate paths")
            if names != sorted(names):
                raise VerificationError("archive paths are not in canonical order")
            if any(not name.startswith(PREFIX) for name in names):
                raise VerificationError("archive entry escapes arena-bridge/ prefix")

            missing = sorted(REQUIRED - set(names))
            if missing:
                raise VerificationError("required files missing: " + ", ".join(missing))
            for info in infos:
                name = info.filename
                if name.startswith(FORBIDDEN_PREFIXES):
                    raise VerificationError(f"forbidden development path: {name}")
                if Path(name).name in FORBIDDEN_BASENAMES:
                    raise VerificationError(f"forbidden runtime artifact: {name}")
                if info.date_time != ZIP_TIMESTAMP:
                    raise VerificationError(
                        f"non-canonical timestamp for {name}: {info.date_time}"
                    )
                mode = (info.external_attr >> 16) & 0xFFFF
                if info.create_system != 3 or not stat.S_ISREG(mode):
                    raise VerificationError(f"non-regular or non-Unix ZIP entry: {name}")
                permissions = stat.S_IMODE(mode)
                if permissions not in {0o644, 0o755}:
                    raise VerificationError(
                        f"non-canonical permissions for {name}: {oct(permissions)}"
                    )

            provenance = _archive_provenance(
                archive,
                expected_version=expected_version,
                expected_source_commit=expected_source_commit,
                expected_candidate_run=expected_candidate_run,
            )
            constants_version, project_version = _archive_version(archive)
            if constants_version != expected_version or project_version != expected_version:
                raise VerificationError(
                    "version mismatch: "
                    f"expected={expected_version}, constants={constants_version}, "
                    f"pyproject={project_version}"
                )
            total_size = sum(info.file_size for info in infos)
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, KeyError) as exc:
        raise VerificationError(f"cannot inspect release ZIP: {exc}") from exc

    return {
        "ok": True,
        "path": path.name,
        "version": expected_version,
        "sha256": _sha256(path),
        "files": len(names),
        "uncompressedBytes": total_size,
        "provenance": provenance,
    }


def verify_pair(versioned: Path, alias: Path, *, expected_version: str,
                expected_source_commit: str | None = None,
                expected_candidate_run: str | None = None) -> dict[str, Any]:
    first = verify_zip(
        versioned,
        expected_version=expected_version,
        expected_source_commit=expected_source_commit,
        expected_candidate_run=expected_candidate_run,
    )
    second = verify_zip(
        alias,
        expected_version=expected_version,
        expected_source_commit=expected_source_commit,
        expected_candidate_run=expected_candidate_run,
    )
    if versioned.read_bytes() != alias.read_bytes():
        raise VerificationError("versioned ZIP and arena-agent.zip are not byte-identical")
    return {
        "ok": True,
        "version": expected_version,
        "sha256": first["sha256"],
        "files": first["files"],
        "uncompressedBytes": first["uncompressedBytes"],
        "artifacts": [versioned.name, alias.name],
        "aliasSha256": second["sha256"],
        "provenance": first["provenance"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versioned", required=True, type=Path)
    parser.add_argument("--alias", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-candidate-run")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_pair(
            args.versioned,
            args.alias,
            expected_version=args.expected_version,
            expected_source_commit=args.expected_source_commit,
            expected_candidate_run=args.expected_candidate_run,
        )
    except VerificationError as exc:
        print(f"release ZIP verification failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
