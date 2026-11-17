"""Full-manifest evidence must reject unchanged vulnerable marker variants."""
from __future__ import annotations

import base64
import json
import sys
from unittest import TestCase

import pytest

from arena import security_alerts as gate, security_manifest_proof as proof

CHECK = TestCase()
HEAD = "a" * 40
BLOB = "b" * 40
PATH = "requirements.txt"
ROW = {"number": 1, "ecosystem": "pip", "manifest_path": PATH,
       "where": "aiohttp", "first_patched_version": "3.14.4", "proof_floor": "3.14.4"}


@pytest.mark.parametrize("text", [
    'aiohttp>=3.14.4; python_version >= "3.12"\naiohttp==3.14.3; python_version < "3.12"',
    "aiohttp==3.14.5\naiohttp==3.14.3",
    "aiohttp>=3.14.4\n-r extra.txt", "aiohttp>=3.14.4\n-c constraints.txt",
    "aiohttp>=3.14.4\n-e git+https://example.test/repo",
    "aiohttp @ https://example.test/wheel.whl", "aiohttp==3.14.4rc1",
    "aiohttp", "aiohttp==3.14.4.*", "",
])
def test_ambiguous_or_vulnerable_full_manifest_is_not_proof(text: str) -> None:
    CHECK.assertFalse(proof.manifest_fixes(PATH, text, "aiohttp", "3.14.4"))


@pytest.mark.parametrize("text", [
    "aiohttp==3.14.5", "aiohttp>=3.14.4,<4", "aiohttp~=3.14.4",
    "aiohttp>=3.14.4\notherpackage",
    "aiohttp>=3.14.4\npython-dateutil==2.9.0.post0",
    'aiohttp>=3.14.4; python_version < "3.12"\naiohttp==3.14.5; python_version >= "3.12"',
    "# generated\naiohttp==3.14.5 \\\n    --hash=sha256:" + "f" * 64 + "\nother==2.0\n",
])
def test_supported_complete_fixed_manifest_is_proof(text: str) -> None:
    CHECK.assertTrue(proof.manifest_fixes(PATH, text, "aiohttp", "3.14.4"))


def test_pyproject_checks_optional_and_marker_variants() -> None:
    text = '''[project]
dependencies = ["aiohttp>=3.14.4"]
[project.optional-dependencies]
old = ["aiohttp==3.14.3; python_version < '3.12'"]
'''
    CHECK.assertFalse(proof.manifest_fixes("pyproject.toml", text, "aiohttp", "3.14.4"))
    CHECK.assertEqual(proof.manifest_fixes("pyproject.toml", text.replace("3.14.3", "3.14.5"),
                                          "aiohttp", "3.14.4"), sys.version_info >= (3, 11))


@pytest.mark.parametrize("text", ['not TOML', '[project]\ndynamic=["dependencies"]',
                                 '[project]\ndependencies="aiohttp>=3.14.4"'])
def test_dynamic_or_malformed_project_is_not_proof(text: str) -> None:
    CHECK.assertFalse(proof.manifest_fixes("pyproject.toml", text, "aiohttp", "3.14.4"))


def _install_evidence(monkeypatch, tmp_path, text: str, *, truncated: bool = False) -> list[str]:
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    (tmp_path / "_github_workflow").mkdir(exist_ok=True)
    event = tmp_path / "_github_workflow" / "event.json"
    event.write_text(json.dumps({"number": 475, "pull_request": {"head": {"sha": HEAD}}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/475/merge")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    # The diff claims a fixed pin; the blob, not that claim, must decide.
    monkeypatch.setattr(gate, "_get", lambda path: ([{
        "filename": PATH, "patch": "+aiohttp==99.0", "status": "modified",
    }], ""))
    seen = []
    def get_object(path):
        seen.append(path)
        if path.startswith("/git/trees/"):
            return {"truncated": truncated, "tree": [{"path": PATH,
                    "sha": BLOB, "mode": "100644", "type": "blob"}]}, ""
        raw = text.encode()
        return {"sha": BLOB, "encoding": "base64", "size": len(raw),
                "content": base64.b64encode(raw).decode()}, ""
    monkeypatch.setattr(gate, "_get_object", get_object)
    return seen


def test_gate_rejects_safe_diff_when_complete_blob_has_vulnerable_variant(monkeypatch, tmp_path) -> None:
    _install_evidence(monkeypatch, tmp_path, "aiohttp>=3.14.4\naiohttp==3.14.3")
    fixed, _ = gate._fixed_dependabot_alerts_by_pr([ROW])
    CHECK.assertEqual(fixed, set())


def test_gate_reads_event_sha_and_caches_exact_blob(monkeypatch, tmp_path) -> None:
    seen = _install_evidence(monkeypatch, tmp_path, "aiohttp>=3.14.4")
    fixed, _ = gate._fixed_dependabot_alerts_by_pr([ROW, dict(ROW, number=2)])
    CHECK.assertEqual(fixed, {"1", "2"})
    CHECK.assertEqual(seen, [f"/git/trees/{HEAD}?recursive=1", f"/git/blobs/{BLOB}"])


def test_gate_retains_alert_on_truncated_tree(monkeypatch, tmp_path) -> None:
    _install_evidence(monkeypatch, tmp_path, "aiohttp>=3.14.4", truncated=True)
    CHECK.assertEqual(gate._fixed_dependabot_alerts_by_pr([ROW])[0], set())


@pytest.mark.parametrize("changes", [
    {"encoding": "none"}, {"sha": "c" * 40}, {"content": "!not-base64!"},
    {"size": 999}, {"size": proof.MAX_MANIFEST_BYTES + 1},
])
def test_bad_or_incomplete_blob_never_counts_as_proof(changes: dict) -> None:
    blob = {"sha": BLOB, "encoding": "base64", "size": 3, "content": "YWJj"}
    blob.update(changes)
    CHECK.assertIsNone(proof.decode_manifest(blob, BLOB))


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_never_follow_symlinks_or_submodules(mode: str) -> None:
    tree = {"truncated": False, "tree": [{"path": "nested", "mode": mode, "type": "blob"}]}
    CHECK.assertEqual(proof.tree_manifest(tree, "nested/requirements.txt")[0], "unknown")


@pytest.mark.parametrize("extra", [
    '[build-system]\nrequires=["aiohttp==3.14.3"]',
    '[dependency-groups]\ndev=["aiohttp==3.14.3"]',
    '[dependency-groups]\ndev=[{include-group="other"}]',
    '[tool.poetry.dependencies]\naiohttp="3.14.3"',
])
def test_additional_build_dev_or_unknown_manager_requirements_are_not_ignored(extra: str) -> None:
    text = '[project]\ndependencies=["aiohttp>=3.14.4"]\n' + extra
    CHECK.assertFalse(proof.manifest_fixes("pyproject.toml", text, "aiohttp", "3.14.4"))


def test_missing_event_sha_never_uses_mutable_pr_head(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_pull_request_number", lambda: "475")
    monkeypatch.setattr(gate, "_event_head_sha", lambda: "")
    monkeypatch.setattr(gate, "_get_object", lambda path: (_ for _ in ()).throw(
        AssertionError("no immutable SHA: must not request a mutable head")))
    CHECK.assertEqual(gate._fixed_dependabot_alerts_by_pr([ROW])[0], set())


def test_deleted_manifest_must_be_absent_in_complete_head_tree(monkeypatch, tmp_path) -> None:
    _install_evidence(monkeypatch, tmp_path, "aiohttp==3.14.3")
    monkeypatch.setattr(gate, "_get", lambda path: ([{
        "filename": PATH, "status": "removed",
    }], ""))
    CHECK.assertEqual(gate._fixed_dependabot_alerts_by_pr([ROW])[0], set())
    monkeypatch.setattr(gate, "_get_object", lambda path: ({"truncated": False, "tree": []}, ""))
    CHECK.assertEqual(gate._fixed_dependabot_alerts_by_pr([ROW])[0], {"1"})


def test_oversized_numeric_component_stays_blocking() -> None:
    CHECK.assertFalse(proof.manifest_fixes(PATH, "aiohttp==" + "9" * 5000, "aiohttp", "3.14.4"))


@pytest.mark.parametrize("note", ["HTTP 403", "unreachable: timeout"])
def test_unreadable_blob_retains_alert_and_surfaces_cached_diagnostic(monkeypatch, tmp_path, note) -> None:
    _install_evidence(monkeypatch, tmp_path, "aiohttp>=3.14.4")
    get_object = gate._get_object
    seen = []
    def fetch(path):
        if path.startswith("/git/blobs/"):
            seen.append(path)
            return None, note
        return get_object(path)
    monkeypatch.setattr(gate, "_get_object", fetch)
    fixed, summary = gate._fixed_dependabot_alerts_by_pr([ROW, dict(ROW, number=2)])
    CHECK.assertEqual(fixed, set())
    CHECK.assertIn(note, summary)
    CHECK.assertIn(BLOB, summary)
    CHECK.assertEqual(summary.count(note), 1)
    CHECK.assertEqual(seen, [f"/git/blobs/{BLOB}"])


def test_invalid_blob_retains_alert_and_reports_rejected_evidence(monkeypatch, tmp_path) -> None:
    _install_evidence(monkeypatch, tmp_path, "aiohttp>=3.14.4")
    get_object = gate._get_object
    monkeypatch.setattr(gate, "_get_object", lambda path: ({"encoding": "none"}, "")
                        if path.startswith("/git/blobs/") else get_object(path))
    fixed, summary = gate._fixed_dependabot_alerts_by_pr([ROW])
    CHECK.assertEqual(fixed, set())
    CHECK.assertIn("invalid or incomplete evidence", summary)
