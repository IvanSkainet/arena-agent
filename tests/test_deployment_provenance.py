"""T55 archive deployment identity parity and bilateral sabotage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.admin.deployment_provenance import (
    DEPLOYED_PROVENANCE,
    RELEASE_PROVENANCE,
    ProvenanceError,
    build_deployed_provenance,
    deployment_id,
    read_deployed_provenance,
    read_deployed_value,
    read_release_provenance,
    write_deployed_provenance,
)


def release(*, commit: str = "a" * 40, tag: str = "v4.170.0",
            run: str = "321") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "repository": "IvanSkainet/arena-agent",
        "sourceCommit": commit,
        "releaseTag": tag,
        "candidateRunId": run,
    }


def deployed(*, rel: dict[str, object] | None = None,
             sha: str = "b" * 64, expected: str | None = "b" * 64,
             previous: dict[str, object] | None = None) -> dict[str, object]:
    identity = rel or release()
    return build_deployed_provenance(
        release=identity,
        tag=str(identity["releaseTag"]),
        downloaded_sha256=sha,
        expected_sha256=expected,
        previous=previous,
        installed_at="2026-08-17T10:00:00Z",
    )


def test_release_identity_is_strict_and_read_from_payload(tmp_path: Path) -> None:
    assert RELEASE_PROVENANCE == ".arena-release-provenance.json"
    assert DEPLOYED_PROVENANCE == "DEPLOYED_PROVENANCE.json"
    (tmp_path / RELEASE_PROVENANCE).write_text(json.dumps(release()), encoding="utf-8")
    assert read_release_provenance(tmp_path) == release()


def test_release_file_read_failures_are_distinct_and_exact(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceError) as missing:
        read_release_provenance(tmp_path)
    assert str(missing.value).startswith("cannot read .arena-release-provenance.json:")
    (tmp_path / RELEASE_PROVENANCE).write_text("[]", encoding="utf-8")
    with pytest.raises(ProvenanceError) as wrong_root:
        read_release_provenance(tmp_path)
    assert str(wrong_root.value) == ".arena-release-provenance.json root must be an object"


def test_release_validation_errors_are_stable_fail_closed_contract() -> None:
    cases = [
        (None, "release provenance root must be an object"),
        ({**release(), "extra": 1}, "release provenance keys do not match the contract"),
        ({**release(), "schemaVersion": 2}, "unsupported release provenance schemaVersion"),
        ({**release(), "repository": "fork/repo"}, "unexpected release provenance repository"),
        ({**release(), "sourceCommit": "bad"}, "sourceCommit must be 40 lowercase hex characters"),
        ({**release(), "releaseTag": 41700}, "releaseTag must be strict vX.Y.Z"),
        ({**release(), "candidateRunId": "0"}, "candidateRunId must be positive decimal or local"),
    ]
    for value, message in cases:
        with pytest.raises(ProvenanceError) as caught:
            build_deployed_provenance(
                release=value, tag="v4.170.0", downloaded_sha256="b" * 64,
                expected_sha256="b" * 64, previous=None,
            )
        assert str(caught.value) == message


@pytest.mark.parametrize("field,value", [
    ("sourceCommit", "A" * 40),
    ("sourceCommit", "a" * 39),
    ("releaseTag", "4.170.0"),
    ("releaseTag", "v4.170"),
    ("candidateRunId", "0"),
    ("candidateRunId", 321),
    ("repository", "attacker/fork"),
    ("schemaVersion", True),
])
def test_substituted_release_identity_is_rejected(field: str, value: object) -> None:
    changed = release()
    changed[field] = value
    with pytest.raises(ProvenanceError):
        build_deployed_provenance(
            release=changed,
            tag="v4.170.0",
            downloaded_sha256="b" * 64,
            expected_sha256="b" * 64,
            previous=None,
        )


def test_wrong_requested_tag_and_wrong_digest_fail_closed() -> None:
    cases = [
        ("v4.170.1", "b" * 64, "b" * 64,
         "requested tag does not match archive releaseTag"),
        ("v4.170.0", "bad", "b" * 64,
         "downloaded SHA-256 is malformed"),
        ("v4.170.0", "b" * 64, "bad",
         "expected SHA-256 is malformed"),
        ("v4.170.0", "c" * 64, "b" * 64,
         "downloaded SHA-256 does not match expected digest"),
    ]
    for tag, actual, expected, message in cases:
        with pytest.raises(ProvenanceError) as caught:
            build_deployed_provenance(
                release=release(), tag=tag,
                downloaded_sha256=actual, expected_sha256=expected,
                previous=None,
            )
        assert str(caught.value) == message


def test_verified_candidate_is_authenticated_but_unverified_or_local_is_not() -> None:
    assert deployed()["authenticated"] is True
    assert deployed(expected=None)["authenticated"] is False
    assert deployed(rel=release(run="local"))["authenticated"] is False


def test_previous_exact_deployment_creates_stable_rollback_identity() -> None:
    old = deployed(rel=release(commit="c" * 40, tag="v4.169.99", run="111"), sha="d" * 64, expected="d" * 64)
    current = deployed(previous=old)
    rollback = current["rollback"]
    assert rollback == {
        "available": True,
        "deploymentId": "4.169.99-" + "d" * 16,
        "path": "backups/deployments/4.169.99-" + "d" * 16,
    }
    assert current["previousDeployment"] == {
        "sourceCommit": "c" * 40,
        "releaseTag": "v4.169.99",
        "candidateRunId": "111",
        "zipSha256": "d" * 64,
        "installedAt": "2026-08-17T10:00:00Z",
        "authenticated": True,
    }
    assert deployment_id(old) == rollback["deploymentId"]


def test_first_identified_deployment_does_not_invent_previous_identity() -> None:
    current = deployed(previous=None)
    assert current == {
        **release(),
        "deploymentModel": "archive",
        "zipSha256": "b" * 64,
        "installedAt": "2026-08-17T10:00:00Z",
        "authenticated": True,
        "previousDeployment": None,
        "rollback": {"available": False, "deploymentId": None, "path": None},
    }


def test_canonical_write_round_trips_and_malformed_disk_state_is_not_trusted(tmp_path: Path) -> None:
    value = deployed()
    path = tmp_path / DEPLOYED_PROVENANCE
    write_deployed_provenance(path, value)
    assert read_deployed_provenance(tmp_path) == value
    assert path.read_bytes().endswith(b"\n")

    changed = dict(value)
    changed["authenticated"] = "yes"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ProvenanceError, match="authenticated"):
        read_deployed_provenance(tmp_path)


def test_deployed_value_direct_root_and_nested_identity_validation() -> None:
    with pytest.raises(ProvenanceError) as caught:
        read_deployed_value([])
    assert str(caught.value) == "deployed provenance root must be an object"

    old = deployed(rel=release(tag="v4.169.99"), sha="d" * 64, expected="d" * 64)
    current = deployed(previous=old)
    assert read_deployed_value(current) == current
    for field in ("sourceCommit", "releaseTag", "candidateRunId", "zipSha256", "installedAt", "authenticated"):
        broken = json.loads(json.dumps(current))
        broken["previousDeployment"].pop(field)
        with pytest.raises(ProvenanceError, match="previousDeployment"):
            read_deployed_value(broken)
    broken = json.loads(json.dumps(current))
    broken["previousDeployment"]["extra"] = 1
    with pytest.raises(ProvenanceError, match="previousDeployment"):
        read_deployed_value(broken)


def test_deployed_record_rejects_every_shape_substitution(tmp_path: Path) -> None:
    base = deployed()
    cases = [
        ([], "DEPLOYED_PROVENANCE.json root must be an object"),
        ({**base, "extra": 1}, "deployed provenance keys do not match the contract"),
        ({**base, "deploymentModel": "git"}, "unexpected deploymentModel"),
        ({**base, "authenticated": "yes"}, "authenticated must be boolean"),
        ({**base, "installedAt": 123}, "installedAt must be a UTC ISO-8601 timestamp"),
        ({**base, "zipSha256": 123}, "zipSha256 must be 64 lowercase hex characters"),
        ({**base, "previousDeployment": []}, "previousDeployment does not match the identity contract"),
        ({**base, "rollback": ["available", "deploymentId", "path"]},
         "rollback does not match the contract"),
        ({**base, "rollback": {"available": "yes", "deploymentId": None, "path": None}},
         "rollback.available must be boolean"),
        ({**base, "rollback": {"available": True, "deploymentId": None, "path": None}},
         "rollback identity does not match previousDeployment"),
    ]
    path = tmp_path / DEPLOYED_PROVENANCE
    for value, message in cases:
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ProvenanceError) as caught:
            read_deployed_provenance(tmp_path)
        assert str(caught.value) == message


def test_default_install_timestamp_is_utc_and_canonical_write_creates_parents(tmp_path: Path) -> None:
    current = build_deployed_provenance(
        release=release(), tag="v4.170.0", downloaded_sha256="b" * 64,
        expected_sha256="b" * 64, previous=None,
    )
    assert current["installedAt"].endswith("Z")
    assert "+00:00" not in current["installedAt"]
    nested = tmp_path / "one" / "two" / DEPLOYED_PROVENANCE
    write_deployed_provenance(nested, current)
    text = nested.read_text(encoding="utf-8")
    assert text == json.dumps(current, sort_keys=True, separators=(",", ":")) + "\n"


def test_absent_deployed_record_is_explicitly_unknown(tmp_path: Path) -> None:
    assert read_deployed_provenance(tmp_path) is None
