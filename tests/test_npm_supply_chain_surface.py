"""The npm dependency surface must stay small, locked and hook-free.

Written on 2026-08-04, the day the Shai-Hulud worm took over the npm
account behind `keyv` and pushed malicious releases across 1,280+
packages with 2 billion monthly installs. That attack is worth
understanding precisely, because two of its properties defeat the
defences people usually reach for:

  * The releases carried **valid provenance signed by GitHub Actions**.
    They genuinely were built by the maintainer's own CI -- the account
    was compromised, not the signature. So "verify the signature" does
    not detect it.
  * The payload ran from a **`preinstall` hook**, before any human or
    scanner looked at the tree. `npm install` alone was enough to leak
    GitHub, npm, AWS, Kubernetes, Vault, Slack, Stripe and SSH secrets.

This project was not affected -- our entire npm tree is `oxlint` plus
its platform binaries, and nothing publishes to npm. These tests exist
so that stays true by construction instead of by luck.

Sabotage record (mandatory per AGENTS.md):
  1. dropping `--ignore-scripts` from ci.yml
     -> test_ci_installs_npm_without_running_scripts fails.
  2. adding a package with `hasInstallScript` to the lock
     -> test_no_dependency_runs_an_install_script fails.
  3. adding a floating `^1.0.0` range to package.json
     -> test_every_dependency_is_pinned_to_an_exact_version fails.
  4. removing `"private": true`
     -> test_we_never_publish_to_npm fails.
"""
from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_JSON = REPO / "package.json"
LOCK_JSON = REPO / "package-lock.json"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"


def _lock() -> dict:
    return json.loads(LOCK_JSON.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The install-hook class of attack.
# ---------------------------------------------------------------------------

def test_no_dependency_runs_an_install_script():
    """`preinstall`/`install`/`postinstall` is how Shai-Hulud executes.

    npm records this per package as `hasInstallScript`. A dependency that
    wants to run code at install time is not automatically malicious, but
    it IS the exact surface the worm used, so it must be a deliberate,
    reviewed decision rather than something that arrives in a lockfile
    bump nobody read.
    """
    offenders = [
        name.replace("node_modules/", "")
        for name, meta in _lock().get("packages", {}).items()
        if name and meta.get("hasInstallScript")
    ]
    assert not offenders, (
        "these dependencies execute code during `npm install`, which is the "
        f"delivery mechanism the Shai-Hulud worm used: {offenders}"
    )


def test_ci_installs_npm_without_running_scripts():
    """Belt and braces: even a hooked package must not get to run."""
    text = CI_YML.read_text(encoding="utf-8")
    # Only executed lines count. The first version of this check matched
    # the prose comment above the step and failed on it -- a detector that
    # flags documentation is one people switch off.
    install_lines = [
        line.strip() for line in text.splitlines()
        if ("npm ci" in line or "npm install" in line)
        and not line.strip().startswith("#")
    ]
    assert install_lines, "expected an npm install step in ci.yml"
    for line in install_lines:
        assert "--ignore-scripts" in line, (
            f"npm install without --ignore-scripts: {line!r}. This is the "
            "one flag that neutralises install-hook supply-chain malware."
        )


def test_ci_never_uses_bare_npm_install():
    """`npm install` can silently resolve past the lock; `npm ci` cannot."""
    text = CI_YML.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "npm install" in stripped:
            pytest.fail(
                f"ci.yml:{lineno} uses `npm install`, which may resolve a "
                "version the committed lockfile never pinned. Use `npm ci`."
            )


# ---------------------------------------------------------------------------
# Keep the surface itself small and pinned.
# ---------------------------------------------------------------------------

def test_every_dependency_is_pinned_to_an_exact_version():
    """A floating range is how a poisoned release reaches you unprompted.

    The compromised `keyv` versions were published as ordinary patch/minor
    releases; anything depending on `^x.y.z` picked them up automatically.
    """
    manifest = _manifest()
    floating = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in (manifest.get(section) or {}).items():
            if not isinstance(spec, str):
                continue
            if spec[:1] in "^~><*" or spec in ("latest", "*", ""):
                floating.append(f"{section}:{name}@{spec}")
    assert not floating, (
        "these specs float, so a compromised upstream release lands without "
        f"a commit here: {floating}"
    )


def test_every_locked_package_carries_an_integrity_hash():
    """Integrity hashes are what make a tampered tarball fail to install."""
    missing = []
    for name, meta in _lock().get("packages", {}).items():
        if not name:  # the root project entry has no resolved tarball
            continue
        if meta.get("link"):
            continue
        if not meta.get("integrity"):
            missing.append(name.replace("node_modules/", ""))
    assert not missing, f"locked packages without an integrity hash: {missing}"


def test_the_npm_surface_stays_small():
    """A ratchet, not a limit for its own sake.

    Every added package is another maintainer account whose compromise
    becomes our problem. 20 entries today (oxlint + its per-platform
    binaries); the headroom is deliberately tight so growth is a decision.
    """
    count = len([n for n in _lock().get("packages", {}) if n])
    assert count <= 40, (
        f"the npm dependency tree grew to {count} packages. Each one is a "
        "maintainer account we implicitly trust -- if this growth is "
        "intentional, raise the ceiling in the same commit and say why."
    )


def test_we_never_publish_to_npm():
    """No publish means no publish token means nothing for a worm to steal.

    Shai-Hulud spreads by stealing npm publish tokens from build runners
    and republishing. We are structurally immune only while this holds.
    """
    assert _manifest().get("private") is True, (
        "package.json must stay `private: true`; publishing would mean "
        "holding an npm token, which is precisely what the worm harvests."
    )


# ---------------------------------------------------------------------------
# The lock must actually describe the manifest.
# ---------------------------------------------------------------------------

def test_lock_is_in_sync_with_the_manifest():
    """A stale lock means `npm ci` installs something nobody reviewed."""
    manifest = _manifest()
    lock = _lock()
    root = lock.get("packages", {}).get("", {})

    for section in ("dependencies", "devDependencies"):
        declared = manifest.get(section) or {}
        locked = root.get(section) or {}
        assert declared == locked, (
            f"package.json {section} and the lockfile disagree: "
            f"{declared} vs {locked}. Run `npm install` and commit the lock."
        )

    for name, spec in (manifest.get("devDependencies") or {}).items():
        entry = lock.get("packages", {}).get(f"node_modules/{name}")
        assert entry is not None, f"{name} is declared but absent from the lock"
        assert entry.get("version") == spec, (
            f"{name} is pinned to {spec} but the lock has "
            f"{entry.get('version')}"
        )
