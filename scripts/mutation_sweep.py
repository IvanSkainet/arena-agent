#!/usr/bin/env python3
"""Run mutation testing over a set of files and write a readable report.

The operator asked for a one-off sweep whose result survives the chat and
does not get cancelled by the next commit. Both are handled outside this
script -- `.github/workflows/mutation-sweep.yml` is `workflow_dispatch`
only, sits in its own concurrency group with `cancel-in-progress: false`,
and uploads the report as an artifact.

What this script adds is picking targets honestly.

**Only files the suite actually executes are worth mutating.** Measured
during the v4.163.0 cycle: `arena/mobile/mirror.py` produced 180 mutants
and killed zero, not because the tests were weak but because coverage
reported "No data to report" for that file -- nothing ran it. A survivor
count on unexecuted code is not a weak signal, it is no signal, and it
costs the same CPU hours as a real one. So targets are filtered by
coverage before anything is mutated.

**Results are cached by content.** `scripts/mutation_cache.py` keys on
(source, its tests, mutmut version), so a re-run after an unrelated
change re-proves only what changed. Measured: 146s cold, 0s cached.

Usage:
    python scripts/mutation_sweep.py                    # gate TARGETS
    python scripts/mutation_sweep.py --paths a.py,b.py
    python scripts/mutation_sweep.py --min-coverage 50
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_cache  # noqa: E402
from mutation_gate import TARGETS  # noqa: E402

CACHE = ROOT / ".mutmut-cache"


def _coverage_map() -> dict[str, float]:
    """percent-covered per file, or {} if no coverage data is available."""
    report = ROOT / ".cov.json"
    if not report.exists():
        return {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {name: meta["summary"]["percent_covered"]
            for name, meta in data.get("files", {}).items()}


def _module_stem(source: str) -> str:
    return Path(source).stem


def _guarding_tests(source: str) -> tuple[str, ...]:
    """Tests declared for this file, or a name-matched guess.

    The gate's TARGETS map is hand-written and authoritative. For a
    whole-tree sweep there is no such map, so tests are matched by
    module name: `arena/mobile/mirror.py` -> any `tests/test_*mirror*`.
    That guess is deliberately narrow. Running the entire suite per
    mutant would be correct and unaffordable (~103k mutants), and a file
    whose name matches nothing is reported as `no-tests-declared`
    instead of being quietly counted as clean.
    """
    declared = TARGETS.get(source)
    if declared:
        return declared
    stem = _module_stem(source)
    if stem in {"__init__", "__main__"}:
        return ()
    tests_dir = ROOT / "tests"
    if not tests_dir.is_dir():
        return ()
    found = sorted(
        f"tests/{p.name}"
        for p in tests_dir.glob("test_*.py")
        if stem in p.stem
    )
    return tuple(found)


def discover_targets() -> dict[str, tuple[str, ...]]:
    """Every mutable module under arena/, with whatever guards it has.

    Ivan asked for a sweep over the whole codebase, accepting that it is
    slow. Slowness is handled by sharding and the content cache, not by
    quietly narrowing the target list.
    """
    targets: dict[str, tuple[str, ...]] = {}
    for path in sorted((ROOT / "arena").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or path.name.startswith("test_"):
            continue
        if path.stat().st_size == 0:
            continue
        targets[rel] = _guarding_tests(rel)
    targets.update(TARGETS)
    return targets


def _run_one(source: str, tests: tuple[str, ...], *,
             timeout: int) -> dict[str, int | str]:
    existing = [t for t in tests if (ROOT / t).exists()]
    if not existing:
        return {"error": "no guarding tests exist"}

    CACHE.unlink(missing_ok=True)
    runner = ("python3 -m pytest -x -q --no-cov -p no:randomly "
              + " ".join(existing))
    started = time.time()
    # mutmut 2.5.1 mutates the file IN PLACE and restores it afterwards.
    # Interrupt it -- per-file timeout, killed job, Ctrl-C -- and the
    # mutant stays on disk. Observed here: a cut-short sweep left
    # `"ok": True` rewritten to `"XXokXX": True` in
    # arena/admin/auto_update.py, and only `git status` caught it. On a
    # whole-tree sweep that is a live risk of committing a mutant, so
    # the original bytes are held and put back unconditionally.
    target = ROOT / source
    original = target.read_bytes()
    try:
        proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
            ["mutmut", "run", "--paths-to-mutate", source,
             "--runner", runner, "--no-progress"],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        target.write_bytes(original)
        return {"error": f"timed out after {timeout}s"}
    finally:
        if target.read_bytes() != original:
            target.write_bytes(original)
    elapsed = int(time.time() - started)

    if not CACHE.exists():
        tail = ((proc.stdout or "")[-400:] + (proc.stderr or "")[-400:])
        return {"error": f"mutmut produced no cache; tail: {tail}"}

    con = sqlite3.connect(CACHE)
    try:
        counts = dict(con.execute(
            "select status, count(*) from Mutant group by status").fetchall())
    finally:
        con.close()

    survived = int(counts.get("bad_survived", 0))
    killed = int(counts.get("ok_killed", 0))
    total = sum(int(v) for v in counts.values())

    # Zero mutants is not a clean result, it is a broken run. The first
    # CI sweep reported "ran, 0/0" for all nine targets in five seconds
    # because dependencies had failed to install and every test died on
    # import -- and the table said "ran" without blinking. Refusing to
    # call that a result is the same rule this release added to the
    # product code, applied to the tooling.
    if total == 0:
        tail = ((proc.stdout or "")[-400:] + (proc.stderr or "")[-400:])
        return {"error": f"zero mutants generated -- mutmut did not run "
                         f"properly; tail: {tail}"}

    result: dict[str, int | str] = {
        "survived": survived, "killed": killed,
        "total": total, "seconds": elapsed,
    }
    if killed == 0:
        # The mirror.py lesson: all-survived means the tests never ran the
        # file, which is a coverage fact dressed up as a mutation score.
        result["warning"] = (
            "nothing was killed -- the listed tests probably do not "
            "execute this file, so the count is meaningless rather than "
            "alarming")
    return result


def _leaked_mutants(sources: list[str]) -> list[str]:
    """Sources that differ from git HEAD after a sweep.

    The per-file restore in `_run_one` covers the paths this script
    controls, but mutmut can also be killed outright -- job cancelled,
    OOM, the runner going away -- and then the mutant it had written is
    simply left there. That is not theoretical: a sweep interrupted in
    this workspace left `0 <= tab_index` rewritten to `1 <= tab_index` in
    arena/browser/cdp_client/tabs_http.py, and it was found by a test
    failing hours later rather than by anything in the sweep.

    So the tree is checked against HEAD at the end and the run fails if
    anything is dirty. Not `git checkout` -- restoring automatically
    would also erase a maintainer's real edits without asking. Report and
    refuse.
    """
    tracked = [s for s in sources if (ROOT / s).exists()]
    if not tracked:
        return []
    try:
        proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
            ["git", "diff", "--name-only", "--", *tracked],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        # No git, or it failed: cannot prove the tree is clean, so do not
        # claim it is. An empty list here would be exactly the
        # "absent means fine" shape this release is about.
        return ["<could not run `git diff` to verify the tree>"]
    if proc.returncode != 0:
        return ["<`git diff` failed; tree state unknown>"]
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="",
                        help="comma-separated sources (default: gate TARGETS)")
    parser.add_argument("--min-coverage", type=float, default=50.0,
                        help="skip files below this %% coverage")
    parser.add_argument("--per-file-timeout", type=int, default=3600)
    parser.add_argument(
        "--all", action="store_true",
        help="sweep every module under arena/, not just the gate TARGETS")
    parser.add_argument(
        "--shard", default="",
        help="N/M -- take only shard N of M when sweeping (1-based)")
    parser.add_argument(
        "--deadline-minutes", type=float, default=0.0,
        help="stop starting new files after this much wall clock (0 = no limit)")
    parser.add_argument("--report", default="mutation-report.md")
    parser.add_argument("--json", dest="json_out", default="mutation-report.json")
    args = parser.parse_args()

    # Argument validation comes BEFORE the toolchain check. `--shard 5/4`
    # is a mistake in the invocation whether or not mutmut is installed,
    # and CI caught the original ordering: a test asserting "a bad shard
    # exits 2" got exit 1 ("mutmut is not installed") on a runner that
    # has no mutmut, which is a different complaint about a different
    # problem. Usage errors first, environment second, work last.
    shard: tuple[int, int] | None = None
    if args.shard.strip():
        index, sep, count = args.shard.partition("/")
        try:
            index_i, count_i = int(index), int(count)
        except ValueError:
            print(f"--shard must look like N/M, got {args.shard!r}",
                  file=sys.stderr)
            return 2
        if not sep or count_i < 1 or not (1 <= index_i <= count_i):
            print(f"--shard {args.shard} is out of range", file=sys.stderr)
            return 2
        shard = (index_i, count_i)

    if shutil.which("mutmut") is None:
        # Not a skip. "The tool is missing" and "the code is fine" are
        # different facts and must not share an exit code.
        print("FAIL: mutmut is not installed (pip install mutmut==2.5.1)",
              file=sys.stderr)
        return 1

    if args.paths.strip():
        targets = {p.strip(): _guarding_tests(p.strip())
                   for p in args.paths.split(",") if p.strip()}
    elif args.all:
        targets = discover_targets()
    else:
        targets = dict(TARGETS)

    if shard is not None:
        index_i, count_i = shard
        ordered = sorted(targets)
        # Deal round-robin over the sorted list: consecutive files in a
        # package tend to cost similarly, so striping spreads the slow
        # ones across shards instead of piling them into the last one.
        picked = ordered[index_i - 1::count_i]
        if not picked:
            print(f"shard {args.shard} selects no files out of "
                  f"{len(ordered)}", file=sys.stderr)
            return 2
        targets = {p: targets[p] for p in picked}

    coverage = _coverage_map()
    rows: list[dict] = []
    sweep_started = time.time()
    deadline = (sweep_started + args.deadline_minutes * 60
                if args.deadline_minutes > 0 else None)
    for source, tests in sorted(targets.items()):
        if deadline is not None and time.time() >= deadline:
            # Out of budget. Say so per file: an unrun file must never
            # read like a file that came back clean.
            rows.append({"source": source, "status": "not-reached-deadline"})
            continue
        if not (ROOT / source).exists():
            rows.append({"source": source, "status": "missing"})
            continue
        covered = coverage.get(source)
        if covered is not None and covered < args.min_coverage:
            rows.append({"source": source, "status": "skipped-low-coverage",
                         "coverage": round(covered, 1)})
            continue
        if not tests:
            rows.append({"source": source, "status": "no-tests-declared"})
            continue

        cached = mutation_cache.lookup(source, tests)
        if cached is not None:
            rows.append({"source": source, "status": "cached",
                         "survived": cached["survived"],
                         "total": cached["total"]})
            continue

        outcome = _run_one(source, tests, timeout=args.per_file_timeout)
        if "error" in outcome:
            rows.append({"source": source, "status": "error",
                         "detail": outcome["error"]})
            continue
        mutation_cache.record(source, tests,
                              survived=int(outcome["survived"]),
                              total=int(outcome["total"]),
                              reason="sweep")
        rows.append({"source": source, "status": "ran", **outcome})

    lines = ["# Mutation sweep", ""]
    lines.append("| file | status | survived | total | seconds |")
    lines.append("|---|---|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| `{row['source']}` | {row['status']} | "
            f"{row.get('survived', '')} | {row.get('total', '')} | "
            f"{row.get('seconds', '')} |")
    warned = [r for r in rows if r.get("warning")]
    if warned:
        lines += ["", "## Warnings", ""]
        for row in warned:
            lines.append(f"* `{row['source']}`: {row['warning']}")
    errored = [r for r in rows if r["status"] == "error"]
    if errored:
        lines += ["", "## Errors", ""]
        for row in errored:
            lines.append(f"* `{row['source']}`: {row['detail']}")

    leaked = _leaked_mutants(sorted(targets))
    if leaked:
        lines += ["", "## MUTANTS LEFT ON DISK", ""]
        for path in leaked:
            lines.append(f"* `{path}` differs from HEAD after the sweep")

    produced = [r for r in rows if r["status"] in ("ran", "cached")]
    lines += [
        "",
        f"{len(produced)} of {len(rows)} files produced a survivor count; "
        f"{len(errored)} errored.",
    ]

    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(rows, indent=1) + "\n",
                                   encoding="utf-8")
    print("\n".join(lines))

    # Fail closed. Sweep #1 reported `ran 0 0 0` for all nine targets and
    # the workflow went green, because this function returned 0 no matter
    # what and the workflow step carried `continue-on-error: true`. A
    # sweep that measured nothing is a broken sweep, and a broken tool
    # that reports success is worse than no tool -- that is the whole
    # thesis of this release.
    if leaked:
        print("FAIL: mutmut left modified sources on disk: "
              + ", ".join(leaked)
              + " -- inspect and `git checkout` them before trusting this tree",
              file=sys.stderr)
        return 1
    if errored:
        print(f"FAIL: {len(errored)} file(s) could not be mutated",
              file=sys.stderr)
        return 1
    if not produced:
        print("FAIL: no file produced a survivor count", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
