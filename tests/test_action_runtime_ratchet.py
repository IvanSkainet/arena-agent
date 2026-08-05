"""Every pinned GitHub Action must be off a retired Node runtime.

GitHub's warning ("target Node.js 20 but are being forced to run on Node
24") only shows in the log of a job that actually ran. dependency-review
runs on pull requests only, so its pin sat on a dead runtime unnoticed
until Ivan read the log by hand. This turns that log line into a red
build.

The check itself is offline: runtimes are recorded per pinned SHA in
`.github/action-runtimes.json`, and a pinned SHA cannot change what it
declares. Refreshing the manifest is the only step that needs network.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "action_runtime_ratchet.py"


def _load():
    spec = importlib.util.spec_from_file_location("action_runtime_ratchet", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def test_no_action_runs_on_a_retired_node_runtime():
    assert mod.check() == 0


def test_every_workflow_pin_is_recorded():
    manifest = mod.load_manifest()
    missing = sorted(set(mod.workflow_refs()) - set(manifest))
    assert not missing, (
        "these pins have no recorded runtime; run "
        "`python scripts/action_runtime_ratchet.py --refresh`: " + ", ".join(missing)
    )


def test_manifest_has_no_stale_entries():
    """A pin that no workflow uses is dead weight that hides real drift."""
    stale = sorted(set(mod.load_manifest()) - set(mod.workflow_refs()))
    assert not stale, "unused pins in the manifest: " + ", ".join(stale)


def test_pins_are_full_commit_shas():
    """A tag pin can be moved onto a node20 build under the same name."""
    loose = [
        ref
        for ref in mod.workflow_refs()
        if len(ref.partition("@")[2]) != 40
        or not all(c in "0123456789abcdef" for c in ref.partition("@")[2])
    ]
    assert not loose, "not pinned by commit SHA: " + ", ".join(sorted(loose))


def test_node20_in_the_manifest_is_rejected(tmp_path, monkeypatch):
    """Sabotage: record a used pin as node20, the ratchet must go red."""
    manifest = dict(mod.load_manifest())
    victim = sorted(mod.workflow_refs())[0]
    manifest[victim] = "node20"
    path = tmp_path / "action-runtimes.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(mod, "MANIFEST", path)
    assert mod.check() == 1


def test_unrecorded_pin_is_rejected(tmp_path, monkeypatch):
    """Sabotage: bump an action without refreshing -- must go red, not pass."""
    manifest = dict(mod.load_manifest())
    manifest.pop(sorted(mod.workflow_refs())[0])
    path = tmp_path / "action-runtimes.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(mod, "MANIFEST", path)
    assert mod.check() == 1


def test_no_workflows_found_is_a_failure(tmp_path, monkeypatch):
    """An empty scan is a broken scanner, not a clean repository."""
    monkeypatch.setattr(mod, "WORKFLOWS", tmp_path / "nowhere")
    assert mod.check() == 1


def test_refresh_refuses_to_write_a_partial_manifest(tmp_path, monkeypatch):
    """If one pin cannot be read, the manifest must not be rewritten.

    A tool that records silence as safety is the exact fail-open shape
    the mutation work is chasing.
    """
    path = tmp_path / "action-runtimes.json"
    monkeypatch.setattr(mod, "MANIFEST", path)

    def boom(ref: str) -> str:
        raise RuntimeError(f"{ref}: pretend the network is down")

    monkeypatch.setattr(mod, "fetch_runtime", boom)
    assert mod.refresh() == 1
    assert not path.exists()


@pytest.mark.parametrize("runtime", ["node12", "node16", "node20"])
def test_deny_list_covers_every_retired_runtime(runtime):
    assert runtime in mod.DENIED


def test_dependency_review_can_write_its_pr_comment():
    """`comment-summary-in-pr: always` needs `pull-requests: write`.

    Without it the action logs "Unable to write summary to pull-request"
    and the CVE report is produced but thrown away -- a review gate that
    reports nothing.
    """
    import re

    text = (ROOT / ".github" / "workflows" / "dependency-review.yml").read_text(
        encoding="utf-8"
    )
    if "comment-summary-in-pr" not in text:
        pytest.skip("workflow no longer asks for a PR comment")
    assert re.search(r"^\s*pull-requests:\s*write\s*$", text, re.MULTILINE), (
        "dependency-review asks for a PR comment but lacks pull-requests: write"
    )
