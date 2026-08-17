"""Archive deployment identity and rollback evidence.

Release ZIPs are not Git checkouts.  The immutable archive carries source
identity in ``.arena-release-provenance.json``; installation adds the archive
SHA-256 and install history in ``DEPLOYED_PROVENANCE.json``.  The latter is
runtime state and is deliberately not embedded in the ZIP (an archive cannot
contain its own digest without a recursive hash problem).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELEASE_PROVENANCE = ".arena-release-provenance.json"
DEPLOYED_PROVENANCE = "DEPLOYED_PROVENANCE.json"
SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_RUN_RE = re.compile(r"[1-9][0-9]*")
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z"
)


class ProvenanceError(ValueError):
    """Release or deployed provenance does not satisfy its strict contract."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError(f"{path.name} root must be an object")
    return value


def validate_release_provenance(value: Any) -> dict[str, Any]:
    """Validate and normalize source identity embedded in a release ZIP."""
    if not isinstance(value, dict):
        raise ProvenanceError("release provenance root must be an object")
    required = {
        "schemaVersion", "repository", "sourceCommit", "releaseTag",
        "candidateRunId",
    }
    if set(value) != required:
        raise ProvenanceError("release provenance keys do not match the contract")
    if value["schemaVersion"] != SCHEMA_VERSION or isinstance(value["schemaVersion"], bool):
        raise ProvenanceError("unsupported release provenance schemaVersion")
    if value["repository"] != "IvanSkainet/arena-agent":
        raise ProvenanceError("unexpected release provenance repository")
    source = value["sourceCommit"]
    tag = value["releaseTag"]
    run = value["candidateRunId"]
    if not isinstance(source, str) or _COMMIT_RE.fullmatch(source) is None:
        raise ProvenanceError("sourceCommit must be 40 lowercase hex characters")
    if not isinstance(tag, str) or _TAG_RE.fullmatch(tag) is None:
        raise ProvenanceError("releaseTag must be strict vX.Y.Z")
    if not isinstance(run, str) or (run != "local" and _RUN_RE.fullmatch(run) is None):
        raise ProvenanceError("candidateRunId must be positive decimal or local")
    return dict(value)


def read_release_provenance(payload_root: Path) -> dict[str, Any]:
    return validate_release_provenance(_read_object(payload_root / RELEASE_PROVENANCE))


def read_deployed_provenance(install_root: Path) -> dict[str, Any] | None:
    """Read deployed identity; malformed state is reported, never trusted."""
    path = install_root / DEPLOYED_PROVENANCE
    if not path.exists():
        return None
    return read_deployed_value(_read_object(path))


def _identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceCommit": value["sourceCommit"],
        "releaseTag": value["releaseTag"],
        "candidateRunId": value["candidateRunId"],
        "zipSha256": value["zipSha256"],
        "installedAt": value["installedAt"],
        "authenticated": value["authenticated"],
    }


def _legacy_deployment_id(value: dict[str, Any]) -> str:
    """Pre-T58 artifact-only identity retained for on-disk compatibility."""
    return f"{value['releaseTag'][1:]}-{value['zipSha256'][:16]}"


def deployment_id(value: dict[str, Any]) -> str:
    """Path-safe identity for one install event of exact archive bytes."""
    event = hashlib.sha256(value["installedAt"].encode("utf-8")).hexdigest()[:12]
    return f"{_legacy_deployment_id(value)}-{event}"


def build_deployed_provenance(
    *,
    release: dict[str, Any],
    tag: str,
    downloaded_sha256: str,
    expected_sha256: str | None,
    authenticated: bool,
    previous: dict[str, Any] | None,
    installed_at: str | None = None,
) -> dict[str, Any]:
    """Bind archive identity to the downloaded bytes and prior deployment."""
    release = validate_release_provenance(release)
    if release["releaseTag"] != tag:
        raise ProvenanceError("requested tag does not match archive releaseTag")
    actual = downloaded_sha256.lower()
    if _SHA256_RE.fullmatch(actual) is None:
        raise ProvenanceError("downloaded SHA-256 is malformed")
    expected = expected_sha256.lower() if expected_sha256 else None
    if expected is not None and _SHA256_RE.fullmatch(expected) is None:
        raise ProvenanceError("expected SHA-256 is malformed")
    if expected is not None and actual != expected:
        raise ProvenanceError("downloaded SHA-256 does not match expected digest")
    if not isinstance(authenticated, bool):
        raise ProvenanceError("authenticated must be boolean")
    if authenticated and (expected is None or release["candidateRunId"] == "local"):
        raise ProvenanceError("authenticated deployment requires trusted release evidence")
    if previous is not None:
        # Refuse to chain history from malformed or unauthenticated-shaped state.
        previous = read_deployed_value(previous)
    timestamp = installed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = dict(release)
    result.update({
        "deploymentModel": "archive",
        "zipSha256": actual,
        "installedAt": timestamp,
        "authenticated": authenticated,
        "previousDeployment": _identity(previous) if previous else None,
        "rollback": {
            "available": previous is not None,
            "deploymentId": deployment_id(previous) if previous else None,
            "path": (
                f"backups/deployments/{deployment_id(previous)}"
                if previous else None
            ),
        },
    })
    return result


def read_deployed_value(value: Any) -> dict[str, Any]:
    """Validate an already parsed deployed record without filesystem tricks."""
    if not isinstance(value, dict):
        raise ProvenanceError("deployed provenance root must be an object")
    # Reuse the file validator through a strict in-memory equivalent.
    required = {
        "schemaVersion", "repository", "sourceCommit", "releaseTag",
        "candidateRunId", "deploymentModel", "zipSha256", "installedAt",
        "authenticated", "previousDeployment", "rollback",
    }
    if set(value) != required:
        raise ProvenanceError("deployed provenance keys do not match the contract")
    if value["deploymentModel"] != "archive":
        raise ProvenanceError("unexpected deploymentModel")
    if not isinstance(value["authenticated"], bool):
        raise ProvenanceError("authenticated must be boolean")
    installed_at = value["installedAt"]
    if not isinstance(installed_at, str) or _TIMESTAMP_RE.fullmatch(installed_at) is None:
        raise ProvenanceError("installedAt must be a UTC ISO-8601 timestamp")
    sha = value["zipSha256"]
    if not isinstance(sha, str) or _SHA256_RE.fullmatch(sha) is None:
        raise ProvenanceError("zipSha256 must be 64 lowercase hex characters")
    validate_release_provenance({key: value[key] for key in (
        "schemaVersion", "repository", "sourceCommit", "releaseTag", "candidateRunId"
    )})
    previous = value["previousDeployment"]
    identity_keys = {
        "sourceCommit", "releaseTag", "candidateRunId", "zipSha256",
        "installedAt", "authenticated",
    }
    if previous is not None:
        if not isinstance(previous, dict) or set(previous) != identity_keys:
            raise ProvenanceError("previousDeployment does not match the identity contract")
        # Validate the nested identity by completing it as a standalone record.
        nested = {
            "schemaVersion": SCHEMA_VERSION,
            "repository": "IvanSkainet/arena-agent",
            "deploymentModel": "archive",
            "previousDeployment": None,
            "rollback": {"available": False, "deploymentId": None, "path": None},
        }
        nested.update(previous)
        read_deployed_value(nested)
    rollback = value["rollback"]
    if not isinstance(rollback, dict) or set(rollback) != {"available", "deploymentId", "path"}:
        raise ProvenanceError("rollback does not match the contract")
    if not isinstance(rollback["available"], bool):
        raise ProvenanceError("rollback.available must be boolean")
    if previous is None:
        valid_rollback = rollback == {
            "available": False, "deploymentId": None, "path": None,
        }
    else:
        # v4.169.48 wrote artifact-only ids. Accept those records without
        # renaming/deleting their snapshots; every new record uses event ids.
        accepted_ids = {deployment_id(previous), _legacy_deployment_id(previous)}
        rollback_id = rollback["deploymentId"]
        valid_rollback = (
            rollback["available"] is True
            and rollback_id in accepted_ids
            and rollback["path"] == f"backups/deployments/{rollback_id}"
        )
    if not valid_rollback:
        raise ProvenanceError("rollback identity does not match previousDeployment")
    return dict(value)


def official_asset_authenticated(
    *, repo: str, trusted_repo: str, tag: str, asset_url: str,
    asset_name: str, sha256: str, fetch_json: Callable[[str], Any],
) -> bool:
    """Bind request parameters to digest metadata controlled by GitHub Releases."""
    if repo != trusted_repo or _TAG_RE.fullmatch(tag) is None:
        return False
    try:
        data = fetch_json(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        )
    except Exception:
        return False
    if not isinstance(data, dict) or data.get("tag_name") != tag:
        return False
    assets = data.get("assets")
    if not isinstance(assets, list):
        return False
    expected_digest = f"sha256:{sha256}"
    return any(
        isinstance(asset, dict)
        and asset.get("name") == asset_name
        and asset.get("browser_download_url") == asset_url
        and isinstance(asset.get("digest"), str)
        and asset["digest"].lower() == expected_digest
        for asset in assets
    )


def quarantine_invalid_deployed_provenance(install_root: Path) -> Path:
    """Preserve malformed runtime history while allowing a valid repair install."""
    source = install_root / DEPLOYED_PROVENANCE
    quarantine = install_root / "backups" / "provenance-quarantine"
    target = quarantine / f"invalid-{time.time_ns()}.json"
    try:
        quarantine.mkdir(parents=True, exist_ok=True)
        quarantine.chmod(0o700)
        os.replace(source, target)
        target.chmod(0o600)
    except OSError as exc:
        raise ProvenanceError(f"cannot quarantine invalid deployed provenance: {exc}") from exc
    return target


def prepare_install_provenance(
    *, payload_root: Path, install_root: Path, staging: Path, tag: str,
    downloaded_sha256: str, expected_sha256: str | None,
    authenticated: bool,
) -> dict[str, Any]:
    """Validate archive/current identity and stage the next deployed record."""
    release = read_release_provenance(payload_root)
    # Validate the incoming identity before mutating malformed historical state.
    build_deployed_provenance(
        release=release,
        tag=tag,
        downloaded_sha256=downloaded_sha256,
        expected_sha256=expected_sha256,
        authenticated=authenticated,
        previous=None,
    )
    quarantine = None
    try:
        previous = read_deployed_provenance(install_root)
    except ProvenanceError:
        quarantine = str(quarantine_invalid_deployed_provenance(install_root))
        previous = None
    deployed = build_deployed_provenance(
        release=release,
        tag=tag,
        downloaded_sha256=downloaded_sha256,
        expected_sha256=expected_sha256,
        authenticated=authenticated,
        previous=previous,
    )
    staged = staging / DEPLOYED_PROVENANCE
    write_deployed_provenance(staged, deployed)
    backup_root = (
        install_root / "backups" / "deployments" / deployment_id(previous)
        if previous is not None else None
    )
    return {
        "deployed": deployed,
        "staged": staged,
        "backup_root": backup_root,
        "history_quarantine": quarantine,
    }


def publish_deployed_provenance(
    provenance_path: Path,
    install_root: Path,
    *,
    backup_root: Path | None,
    timestamp: int,
) -> list[tuple[Path, Path]]:
    """Publish provenance last and return any previous-record restore pair."""
    if not provenance_path.is_file():
        raise ProvenanceError("staged deployed provenance is missing")
    destination = Path(install_root) / DEPLOYED_PROVENANCE
    backup = (
        backup_root / DEPLOYED_PROVENANCE if backup_root is not None
        else Path(install_root) / f".{DEPLOYED_PROVENANCE}.old-{timestamp}"
    )
    restore: list[tuple[Path, Path]] = []
    if destination.exists():
        destination.rename(backup)
        restore.append((backup, destination))
    shutil.move(str(provenance_path), str(destination))
    return restore


def write_deployed_provenance(path: Path, value: dict[str, Any]) -> None:
    """Write canonical bytes to staging; the platform mover publishes them."""
    checked = read_deployed_value(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(checked, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise ProvenanceError(f"cannot restrict deployed provenance permissions: {exc}") from exc
