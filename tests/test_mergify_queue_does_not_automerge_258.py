"""The merge queue may update and re-check, but it may never decide to merge.

Why this file exists
--------------------
`.mergify.yml` (item 2 of #258) exists to remove one specific manual cost:
the `master` ruleset sets `strict_required_status_checks_policy: true`, so
every merge makes every other open pull request out of date, and each one
then has to be updated by hand and re-run through ~80 checks. The queue does
that serially and by itself.

What it must never do is decide that a pull request is ready. Green CI is
not this project's merge criterion. Every merge here also requires a full
pytest run on the operator's Windows machine, compared against a same-day
master baseline **by test id**, because a large set of tests only fails on
real hardware and never in CI -- `tests/e2e/test_bridge_live.py`,
`tests/test_desktop_windows_backend.py`, the mobile on-device suite. No
condition expressible in a Mergify configuration can observe that run.

So `auto_merge_conditions` (and its deprecated predecessor `auto_merge`)
would not be a convenience here: it would swap the merge criterion for a
weaker one that looks identical from the outside. Enabling it is a one-line
edit that breaks nothing visible and produces its first bad merge only when
a Windows-only regression happens to be in flight -- the green-checkmark
fallacy AGENTS.md names. Hence a gate rather than a comment.

The same reasoning covers the `merge` and `queue` actions in
`pull_request_rules`: a rule that queues or merges on conditions is
auto-merge written the long way.
"""

from __future__ import annotations

import pathlib

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    # A raise, not a skip. A gate that evaporates when a dependency is
    # missing reports success exactly where nobody is looking.
    raise RuntimeError(
        "PyYAML is required for the Mergify configuration gate; without it "
        "this test would skip and the audit would pass by default"
    ) from exc

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".mergify.yml"

# Actions that merge a pull request, or enqueue it for merging, without a
# human having said so on that specific revision.
DECIDING_ACTIONS = ("merge", "queue")

# Both spellings: `auto_merge` is deprecated in favour of
# `auto_merge_conditions`, and a deprecated key that still works is still a
# way to turn this on.
AUTO_MERGE_KEYS = ("auto_merge", "auto_merge_conditions")


def _copied_check_conditions(rule: dict, field: str) -> list[str]:
    """Conditions in `field` that restate a required check.

    Lifted out of the assertion loop on purpose: a comprehension nested
    inside two `for` levels reads as one expression but is three, and
    CodeScene flags exactly that shape ("Bumpy Road Ahead") even in tests.
    """
    return [
        str(condition)
        for condition in rule.get(field) or []
        if "check-success" in str(condition)
    ]


def _config() -> dict:
    assert CONFIG.is_file(), (
        ".mergify.yml is missing. If the merge queue was removed on purpose, "
        "remove this gate in the same change and say why in the commit; a "
        "silently absent config means PRs go back to being updated by hand."
    )
    loaded = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f".mergify.yml is not a mapping: {type(loaded)}"
    return loaded


def test_auto_merge_is_not_configured() -> None:
    """Neither spelling of auto-merge may appear, at any value."""
    settings = _config().get("merge_protections_settings") or {}
    for key in AUTO_MERGE_KEYS:
        assert key not in settings, (
            f"merge_protections_settings.{key} is set. Mergify would then "
            "merge on green CI, but green CI is not the merge criterion here: "
            "every merge also requires a full live pytest run on the "
            "operator's machine, compared to a master baseline by test id. "
            "Nothing in this file can see that run, so this setting replaces "
            "the real criterion with a weaker one that looks the same."
        )


def test_no_rule_merges_or_queues_on_conditions() -> None:
    """`pull_request_rules` may label and comment; it may not decide."""
    for rule in _config().get("pull_request_rules") or []:
        actions = rule.get("actions") or {}
        for action in DECIDING_ACTIONS:
            assert action not in actions, (
                f"pull request rule {rule.get('name')!r} carries the "
                f"{action!r} action. A rule that {action}s on conditions is "
                "auto-merge written the long way: it decides readiness from "
                "signals that do not include the live run on the operator's "
                "machine. Entry into the queue stays a human act "
                "(`@mergifyio queue`, or the checkbox Mergify posts)."
            )


def test_the_queue_stays_serial() -> None:
    """One pull request at a time, so a red queue run names its culprit.

    Not a style preference. With batching or speculative checks a failure
    belongs to a set of pull requests and has to be bisected to attribute,
    and each parallel check is a full ~80-check matrix on shared runners.
    This repository merges a handful of pull requests a week; there is
    nothing here for parallelism to buy.
    """
    config = _config()
    queue = config.get("merge_queue") or {}
    assert queue.get("max_parallel_checks") == 1, (
        "merge_queue.max_parallel_checks must be 1: speculative checks "
        f"multiply the matrix, got {queue.get('max_parallel_checks')!r}"
    )
    assert queue.get("mode", "serial") == "serial", (
        f"merge_queue.mode must be serial, got {queue.get('mode')!r}"
    )
    for rule in config.get("queue_rules") or []:
        assert rule.get("batch_size", 1) == 1, (
            f"queue rule {rule.get('name')!r} batches "
            f"{rule.get('batch_size')!r} pull requests; a batch failure then "
            "has to be bisected before anyone knows whose change broke it"
        )


def test_required_checks_are_not_duplicated_into_this_file() -> None:
    """The ruleset is the one list of required checks.

    `branch_protection_injection_mode` defaults to `queue`, which injects the
    repository's branch-protection conditions as queue and merge conditions.
    Restating them here would create a second list that drifts from the
    first, and a check added to the ruleset but forgotten here would quietly
    stop gating queued merges. That is the same shape as #307: something
    leaves one gate's reach and nobody notices.
    """
    for rule in _config().get("queue_rules") or []:
        assert rule.get("branch_protection_injection_mode", "queue") == "queue", (
            f"queue rule {rule.get('name')!r} disables branch-protection "
            "injection; the ruleset's required checks would then not gate "
            "queued merges at all"
        )
        for field in ("queue_conditions", "merge_conditions"):
            copied = _copied_check_conditions(rule, field)
            assert not copied, (
                f"queue rule {rule.get('name')!r} lists check-success "
                f"conditions in {field}: {copied}. Those come from the "
                "ruleset by injection; a second copy here is a list that "
                "drifts."
            )


def test_a_dequeued_pull_request_is_labelled() -> None:
    """A rejection has to be visible on the pull request itself.

    A pull request the queue dropped still shows its own green checks -- from
    its old base. Without a label the only trace is a comment that scrolls
    away, and the next reader sees an open, green, apparently mergeable pull
    request. That is precisely the confusion the queue was added to prevent.
    """
    queue = _config().get("merge_queue") or {}
    assert queue.get("dequeued_label"), (
        "merge_queue.dequeued_label is unset or empty; a dropped pull request "
        "would look identical to a healthy one"
    )
