#!/usr/bin/env python3
"""Keep every pinned GitHub Action off a deprecated Node runtime.

GitHub stopped shipping Node 20 on its runners: an action that declares
`using: node20` is silently forced onto Node 24 today and will simply
stop working later. The warning only appears in the log of a job that
actually runs, so a rarely-triggered workflow (dependency-review runs on
pull requests only) can sit on a dead runtime for months unnoticed.

Actions are pinned by commit SHA here, so the runtime a given pin
declares is a fixed fact. This script records that fact in
`.github/action-runtimes.json`, keyed by `owner/repo@sha`, and fails when

  * a workflow uses a pin that is not in the manifest -- somebody bumped
    or added an action without looking at what runtime it declares, or
  * a recorded runtime is on the deny list (node16, node20).

The check itself is offline and deterministic; only `--refresh` touches
the network, and it refuses to write a manifest it could not verify.

Usage:
    python scripts/action_runtime_ratchet.py            # check
    python scripts/action_runtime_ratchet.py --refresh  # re-read from GitHub
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
MANIFEST = ROOT / ".github" / "action-runtimes.json"

# Runtimes GitHub has retired or announced as retiring. `composite` and
# `docker` actions carry no Node runtime and are recorded as such.
DENIED = {"node12", "node16", "node20"}

USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
USING_RE = re.compile(r"^\s+using:\s*['\"]?([A-Za-z0-9]+)['\"]?\s*$", re.MULTILINE)


def workflow_refs() -> dict[str, list[str]]:
    """Map `owner/repo@sha` -> workflow files that use it."""
    refs: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for ref in USES_RE.findall(path.read_text(encoding="utf-8")):
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            refs.setdefault(ref, []).append(path.name)
    return refs


def load_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _get(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310  # nosec B310 -- fixed api.github.com endpoint for action metadata
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return None
    except OSError:
        return None


def fetch_runtime(ref: str) -> str:
    """Read `runs.using` straight from the pinned commit. Network.

    An action without any action.yml is still valid: the runner falls
    back to building the repository's Dockerfile (rhysd/actionlint ships
    exactly that way, and its job log shows "Build container for action
    use: .../Dockerfile"). That is a container action with no Node
    runtime at all, so it is recorded as `dockerfile` rather than
    treated as an unreadable pin.
    """
    repo, _, sha = ref.partition("@")
    parts = repo.split("/")
    owner_repo = "/".join(parts[:2])
    subdir = "/".join(parts[2:])
    prefix = f"{subdir}/" if subdir else ""
    base = f"https://raw.githubusercontent.com/{owner_repo}/{sha}/{prefix}"
    seen_metadata = False
    for name in ("action.yml", "action.yaml"):
        body = _get(base + name)
        if body is None:
            continue
        seen_metadata = True
        match = USING_RE.search(body)
        if match:
            return match.group(1).lower()
    if seen_metadata:
        raise RuntimeError(f"{ref}: action metadata has no runs.using")
    if _get(base + "Dockerfile") is not None:
        return "dockerfile"
    raise RuntimeError(f"{ref}: no action.yml, action.yaml or Dockerfile at that commit")


def refresh() -> int:
    manifest = load_manifest()
    failures = []
    for ref in sorted(workflow_refs()):
        try:
            manifest[ref] = fetch_runtime(ref)
        except RuntimeError as exc:
            failures.append(str(exc))
    if failures:
        # A manifest written from partial data would record silence as
        # safety, which is the exact failure mode this guards against.
        for line in failures:
            print(f"refresh failed: {line}", file=sys.stderr)
        return 1
    used = set(workflow_refs())
    manifest = {k: v for k, v in manifest.items() if k in used}
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"recorded {len(manifest)} action pins in {MANIFEST.relative_to(ROOT)}")
    return 0


def check() -> int:
    refs = workflow_refs()
    if not refs:
        print("no `uses:` pins found -- refusing to pass", file=sys.stderr)
        return 1
    manifest = load_manifest()
    problems = []
    for ref, files in sorted(refs.items()):
        where = ", ".join(sorted(set(files)))
        runtime = manifest.get(ref)
        if runtime is None:
            problems.append(
                f"{ref} ({where}): not in {MANIFEST.name}. "
                f"Run: python scripts/action_runtime_ratchet.py --refresh"
            )
        elif runtime in DENIED:
            problems.append(f"{ref} ({where}): runs on {runtime}, which GitHub retired")
    if problems:
        print("Deprecated or unrecorded action runtimes:\n", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"{len(refs)} action pins, none on a retired Node runtime")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="re-read runtimes from GitHub (network)"
    )
    args = parser.parse_args()
    return refresh() if args.refresh else check()


if __name__ == "__main__":
    raise SystemExit(main())
