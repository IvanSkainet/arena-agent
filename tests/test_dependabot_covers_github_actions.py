"""Every action in a workflow is SHA-pinned, so alerts cannot see them.

Why this test exists
--------------------
All 25 third-party actions in `.github/workflows/` are pinned to full 40-char
commit SHAs. That is the right call for supply-chain integrity, and it has one
documented consequence that is easy to forget:

    "Dependabot will only create Dependabot alerts for vulnerable GitHub
     Actions that use semantic versioning. You will not receive alerts for a
     vulnerable action that uses SHA versioning."
        -- docs.github.com, About Dependabot alerts, Limitations

Measured on this repository, not assumed: all 25 actions appear in the
dependency graph, and every one records a 40-char SHA as its version -- zero
semver entries. Dependabot alerts and automated security fixes are both
enabled, and across the repository's entire history they produced two alerts,
one pip and one npm. Never an action.

GitHub's documented remedy is Dependabot *version* updates for the
`github-actions` ecosystem: it resolves each SHA back to its release and
proposes the next one, so an upstream security fix still arrives as a pull
request even though no alert can fire.

That makes the `github-actions` entry in `.github/dependabot.yml` load-bearing
security configuration rather than housekeeping. Deleting it restores silence
without breaking anything visible -- verified: removing the whole block left
the suite green before this file existed. Hence the gate.
"""

from __future__ import annotations

import pathlib
import re

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    # A `raise`, not importorskip: a security gate that evaporates when a
    # dependency is missing reports success exactly where nobody is looking.
    raise RuntimeError(
        "PyYAML is required for the dependabot coverage gate; without it this "
        "test would skip and the audit would pass by default"
    ) from exc

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# `uses: owner/repo@ref` -- ignores commented-out lines.
_USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")


def _updates() -> list[dict]:
    with DEPENDABOT.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    updates = config.get("updates")
    if not isinstance(updates, list) or not updates:
        raise RuntimeError(f"{DEPENDABOT} declares no `updates:` list")
    return updates


def _third_party_uses() -> list[str]:
    """Every `uses:` reference that points outside this repository."""
    refs = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for ref in _USES.findall(path.read_text(encoding="utf-8")):
            # `./local-action` and `owner/repo/.github/workflows/x.yml@ref`
            # for this same repo are not third-party dependencies.
            if ref.startswith("./") or ref.startswith("IvanSkainet/arena-agent"):
                continue
            refs.append(ref)
    return refs


def test_dependabot_watches_the_github_actions_ecosystem() -> None:
    """Without this entry, nothing reports a vulnerable pinned action."""
    ecosystems = {u.get("package-ecosystem") for u in _updates()}

    assert "github-actions" in ecosystems, (
        "`.github/dependabot.yml` has no `github-actions` entry. Every action "
        "in this repository is SHA-pinned, and Dependabot alerts do not fire "
        "for SHA-versioned actions -- version updates are the only channel "
        "that reports an upstream security fix. Removing this entry makes the "
        f"actions supply chain silent. Configured ecosystems: {sorted(e for e in ecosystems if e)}."
    )


def test_actions_updates_are_not_grouped() -> None:
    """Grouping hides several supply-chain decisions behind one diff.

    A pip bump is a version change; an action bump means trusting a new commit
    in someone else's repository. Each one has to be reviewed the way the
    original pin was, which a grouped diff actively prevents.
    """
    for update in _updates():
        if update.get("package-ecosystem") != "github-actions":
            continue
        assert not update.get("groups"), (
            "the github-actions entry defines `groups:`. Each action bump is a "
            "separate decision to trust a new upstream commit and needs its own "
            "reviewable diff; grouping collapses several into one."
        )


def test_every_ecosystem_waits_out_a_cooldown() -> None:
    """Do not offer a version that was published minutes ago.

    Without `cooldown`, Dependabot proposes a release the moment it appears --
    which is the window a supply-chain attacker needs. The tj-actions and npm
    chalk/debug compromises were both live for well under a day before being
    caught and yanked, so a week's delay means the malicious version is gone
    before it is ever offered.

    zizmor's `dependabot-cooldown` audit raised this on #164, against the
    pre-existing pip block as well as the new actions one. It surfaced as a
    code-scanning alert rather than a failed job -- the required check exited
    0 while the SARIF upload reported the warning, the same split documented
    in #162.
    """
    for update in _updates():
        eco = update.get("package-ecosystem")
        cooldown = update.get("cooldown") or {}
        days = cooldown.get("default-days")
        assert isinstance(days, int) and days >= 7, (
            f"the {eco} entry sets cooldown default-days={days!r}; it must be at "
            f"least 7 so a freshly published (and possibly malicious) release is "
            f"never proposed before the ecosystem has had time to catch it."
        )


def test_the_premise_still_holds_every_action_is_sha_pinned() -> None:
    """If actions were tag-pinned, alerts would work and this gate would be moot.

    This is the assumption the whole file rests on. Asserting it means the
    reasoning above cannot quietly go stale: should the repository ever move to
    semver tags, this fails and the comments get revisited rather than believed.
    """
    refs = _third_party_uses()
    assert refs, "no third-party `uses:` found -- the parser is probably broken"

    unpinned = [ref for ref in refs if not _SHA_PIN.search(ref)]
    assert not unpinned, (
        f"these actions are not pinned to a 40-character commit SHA: {unpinned}. "
        f"Either pin them, or -- if the repository has deliberately moved to "
        f"immutable semver tags -- revisit this file, because Dependabot alerts "
        f"do work for semver-versioned actions."
    )
