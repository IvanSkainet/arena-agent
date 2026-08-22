"""Workflow-level write scopes are inherited by every job added later.

Why this test exists
--------------------
Issue #162: the required zizmor check runs in the default persona, which
suppresses its ``excessive-permissions`` audit entirely. Three high-severity
findings (``stale.yml`` granting ``issues: write`` + ``pull-requests: write``,
``dependency-review.yml`` granting ``pull-requests: write``, all at workflow
level) sat in the tree while the gate reported success.

Moving those scopes down to the job that uses them fixes the finding, but the
fix is one careless edit away from being undone: reverting it was verified to
keep the whole suite green, because nothing here asserted the shape. A fix with
no gate is a fix with a expiry date, so this is the gate.

The rule is deliberately narrow. It does not forbid write scopes -- ``stale``
genuinely needs to close issues, ``dependency-review`` genuinely needs to
comment on pull requests. It forbids granting them *where an unrelated future
job would silently inherit them*.

``contents: read`` is exempt: it is the least privilege a checkout needs, it
grants nothing an inheriting job could abuse, and several workflows set it at
the top as a deliberate read-only default.
"""

from __future__ import annotations

import pathlib

import pytest

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    # Deliberately NOT importorskip: a security gate that silently evaporates
    # when a dependency is missing is a gate that reports success on the one
    # environment where nobody checked. PyYAML is in the test requirements.
    raise RuntimeError(
        "PyYAML is required for the workflow-permissions gate; without it this "
        "test would skip and the audit would pass by default"
    ) from exc

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Read-only scopes are safe to inherit: they cannot mutate the repository.
_HARMLESS_TO_INHERIT = {"read", "none"}

# `permissions:` also accepts a bare scalar. `write-all` grants every scope at
# once -- the single most dangerous value the key can take -- and `read-all` is
# the safe counterpart. An earlier revision of this test only inspected the
# mapping form, so `permissions: write-all` passed the gate untouched; three
# reviewers caught it on #163. Scalars are now checked explicitly.
_SAFE_SCALARS = {"read-all", "{}"}


def _workflow_files() -> list[pathlib.Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflow files found under {WORKFLOWS}"
    return files


def _load(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_no_write_scopes_at_workflow_level(path: pathlib.Path) -> None:
    """A write scope at workflow level leaks into every job in the file."""
    doc = _load(path)

    if "permissions" not in doc:
        # Covered by test_every_workflow_pins_a_permissions_baseline.
        return

    permissions = doc["permissions"]

    # Scalar form: `permissions: write-all` / `read-all`. YAML hands back a
    # plain string, which an isinstance(dict) check skips straight past.
    if isinstance(permissions, str):
        assert permissions.strip().lower() in _SAFE_SCALARS, (
            f"{path.name} sets `permissions: {permissions}` at workflow level, "
            f"granting every scope to every job in the file. Use "
            f"`permissions: {{}}` at the top and grant scopes per job "
            f"(see issue #162)."
        )
        return

    if not isinstance(permissions, dict):
        raise AssertionError(
            f"{path.name} has an unrecognised `permissions:` form "
            f"({permissions!r}); expected a mapping or a scalar."
        )

    offenders = {
        scope: level
        for scope, level in permissions.items()
        if str(level).strip().lower() not in _HARMLESS_TO_INHERIT
    }

    assert not offenders, (
        f"{path.name} grants {offenders} at workflow level, so every job in the "
        f"file inherits it -- including jobs added later by someone who never "
        f"considered the token. Move these scopes onto the job that uses them "
        f"and leave `permissions: {{}}` at the top (see issue #162)."
    )


def test_every_workflow_pins_a_permissions_baseline() -> None:
    """No workflow may fall back to the repository-wide default token.

    Omitting `permissions:` entirely means the job runs with whatever the
    repository default happens to be -- a setting that lives outside the
    repository and can be widened without a commit. Every workflow states its
    own baseline, even if that baseline is `{}`.

    This deliberately does NOT require a block on every individual job. Jobs
    inheriting a read-only workflow baseline (`contents: read` or `{}`) already
    have least privilege, and demanding boilerplate on all 27 of them would be
    noise -- the kind that gets a gate deleted rather than obeyed.
    """
    missing = [p.name for p in _workflow_files() if "permissions" not in _load(p)]

    assert not missing, (
        f"workflow(s) {missing} declare no `permissions:` at all, so they inherit "
        f"the repository-wide default token. State a baseline explicitly -- use "
        f"`permissions: {{}}` and grant scopes per job (issue #162)."
    )
