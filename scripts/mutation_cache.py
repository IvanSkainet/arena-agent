#!/usr/bin/env python3
"""Content-addressed cache so mutation testing only re-runs what changed.

The operator's question was the right one: a full mutation run over
``arena/`` is ~103,000 mutants and ~26 CPU-hours, and almost all of that
work re-proves things that were already proven. Why grind code nobody
touched?

So results are keyed by a hash of **(source file, the tests that guard
it, the mutmut version)**. All three matter:

* source changes -> the mutants themselves change;
* test changes -> the same mutants may now be caught, or stop being
  caught, which is exactly the regression worth catching;
* tool changes -> a different mutmut generates a different mutant set,
  so an old count is not comparable.

Two rules keep this honest rather than merely fast.

**A cache miss is never a pass.** An unknown key means the file must be
run, not waved through. Anything else turns a cache into a way to stop
testing.

**A cache hit still ratchets.** The stored survivor count is compared
against the baseline exactly as a fresh run would be, so lowering the
baseline while skipping the run is not possible.

The entry also records *why* it was accepted, because a number with no
provenance is a number nobody trusts six months later.

Usage:
    python scripts/mutation_cache.py --key arena/files/sandbox.py
    python scripts/mutation_cache.py --stale        # what needs a run
    python scripts/mutation_cache.py --prune        # drop dead entries
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "scripts" / "mutation_cache.json"


def tool_version() -> str:
    """mutmut's version, or a marker that keeps everything stale.

    Failing to a sentinel rather than a guess means a broken toolchain
    invalidates the cache instead of silently blessing it.
    """
    # Read the installed distribution's metadata rather than shelling out:
    # mutmut 2.5.1 has no `--version` flag, and the first run of this
    # recorded its usage banner as the "version" -- a string that never
    # changes between releases, which would have silently disabled the
    # tool-version half of the cache key.
    try:
        from importlib.metadata import version
        return f"mutmut {version('mutmut')}"
    except Exception:
        pass
    try:
        out = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
            [sys.executable, "-m", "mutmut", "version"],
            capture_output=True, text=True, timeout=60,
        )
        text = (out.stdout or out.stderr or "").strip().splitlines()
        first = text[0][:80] if text else ""
        if first and "Usage:" not in first:
            return first
    except Exception:
        pass
    return "unavailable"


def fingerprint(source: str, tests: tuple[str, ...] | list[str],
                *, tool: str | None = None) -> str:
    """Hash of everything whose change could change the verdict."""
    h = hashlib.sha256()
    h.update((tool if tool is not None else tool_version()).encode())
    for rel in [source, *sorted(tests)]:
        path = ROOT / rel
        h.update(rel.encode())
        h.update(b"\0")
        if path.exists():
            h.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            # A missing guard test must not hash the same as an empty
            # one; it should force a run (which then fails closed).
            h.update(b"MISSING")
        h.update(b"\0")
    return h.hexdigest()


def load() -> dict:
    if not CACHE_FILE.exists():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        # A corrupt cache means "run everything", never "skip everything".
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict) or "entries" not in data:
        return {"version": 1, "entries": {}}
    return data


def save(data: dict) -> None:
    CACHE_FILE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")


def lookup(source: str, tests: tuple[str, ...] | list[str]) -> dict | None:
    """Return the cached result for this exact input, or None."""
    entry = load()["entries"].get(source)
    if not entry:
        return None
    if entry.get("fingerprint") != fingerprint(source, tests):
        return None
    return entry


def record(source: str, tests: tuple[str, ...] | list[str], *,
           survived: int, total: int, reason: str = "fresh run") -> None:
    data = load()
    data["entries"][source] = {
        "fingerprint": fingerprint(source, tests),
        "survived": int(survived),
        "total": int(total),
        "tests": sorted(tests),
        "tool": tool_version(),
        "reason": reason,
    }
    save(data)


def stale(targets: dict[str, tuple[str, ...]]) -> list[str]:
    """Sources whose cached result no longer applies."""
    return [src for src, tests in sorted(targets.items())
            if lookup(src, tests) is None]


def main() -> int:
    from mutation_gate import TARGETS  # noqa: PLC0415 - avoids a cycle

    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="print the fingerprint for one source")
    ap.add_argument("--stale", action="store_true",
                    help="list sources that need a run")
    ap.add_argument("--prune", action="store_true",
                    help="drop entries for sources no longer targeted")
    args = ap.parse_args()

    if args.key:
        tests = TARGETS.get(args.key, ())
        print(fingerprint(args.key, tests))
        return 0

    if args.prune:
        data = load()
        dropped = [k for k in data["entries"] if k not in TARGETS]
        for k in dropped:
            del data["entries"][k]
        save(data)
        print(f"pruned {len(dropped)} entr{'y' if len(dropped) == 1 else 'ies'}")
        return 0

    needs = stale(TARGETS)
    if args.stale:
        for src in needs:
            print(src)
        return 0

    cached = len(TARGETS) - len(needs)
    print(f"{cached}/{len(TARGETS)} target(s) cached, {len(needs)} need a run")
    for src in needs:
        print(f"  stale: {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
