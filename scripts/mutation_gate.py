#!/usr/bin/env python3
"""Mutation gate: prove the security tests notice when the code changes.

Why this exists, in one measurement. On 2026-08-04 this repository had 406
test files. Six mentioned sabotage. AGENTS.md did not contain the word --
the "sabotage every new gate" rule lived only in a conversation.

The operator's argument settled it: a convention depends on an agent
choosing to follow it, a red CI job does not. Agents skip conventions they
were not forced into; they do not skip failing builds.

Pointed at ``arena/files/sandbox.py``, mutmut found 216 mutants and 95
survivors. Most were harmless -- error-message wording, or the second half
of a defence-in-depth pair (breaking the ``..`` check still leaves the
resolve-and-compare check; verified by applying that mutant and watching
traversal stay refused). One was not:

    -    if target_path.resolve() == bridge_py.resolve():
    +    if target_path.resolve() != bridge_py.resolve():

One flipped operator inverts the bridge's self-protection:

    edit the bridge itself  ->  200  (allowed)
    edit an ordinary file   ->  403  "cannot edit the bridge itself"

An agent could rewrite ``unified_bridge.py`` -- every policy and audit call
in it -- while ordinary work broke. All 406 test files passed, because
nothing asserted that the bridge protects itself in *either* direction.
``tests/test_bridge_self_protection.py`` now does; five of its tests catch
that mutant.

**Scope is narrow on purpose, and the number is measured.** Mutating one
file takes ~2 minutes; the whole ``arena/`` tree (41,436 statements) would
take ~13 hours and produce a figure nobody reads. This gate covers the file
where a surviving mutant most directly means "a security decision can be
silently wrong", and the baseline ratchets: the count may fall, never rise.

Usage:
    python scripts/mutation_gate.py                 # check against baseline
    python scripts/mutation_gate.py --write-baseline
    python scripts/mutation_gate.py --list          # show survivors
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_cache  # noqa: E402 -- needs the path line above

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "mutation_baseline.json"
CACHE = ROOT / ".mutmut-cache"

# source file -> tests that actually import and exercise it. Pointing this at
# tests that do not touch the file produces a meaningless 100% survival rate;
# that mistake was made once while building this and is why the check below
# refuses a run where nothing dies.
TARGETS: dict[str, tuple[str, ...]] = {
    "arena/files/sandbox.py": (
        "tests/test_write_is_not_code_execution.py",
        "tests/test_bridge_self_protection.py",
        "tests/test_files_sandbox_v442_hardening.py",
        # v4.169.33: blocklist-parity tests; with these the survivor count
        # is 0/208 (was 89/216 -- refusal-set entries, statuses and
        # sentinel messages are now all behaviourally pinned).
        "tests/test_files_sandbox_parity_v4_169_33.py",
    ),
    # v4.169.34: BrowserAct discovery helpers, 155/196 survivors before the
    # parity file existed -- every probe was env-dependent and nearly no
    # observable was pinned. Two equivalent families were proven dead code
    # and removed from the module (unreachable `not path` guard; the
    # `"\\uv/tools/"` disjunct subsumed by `"uv/tools" in path`). The rest is
    # behaviourally pinned: per-OS candidate lists, source classification
    # matrix, version-parse matrix, exact hint strings, status/doctor dicts,
    # and both subprocess contracts (argv + kwargs capture).
    "arena/admin/browseract.py": (
        "tests/test_browseract.py",
        "tests/test_browseract_browse_backend.py",
        "tests/test_browseract_error_diagnostics.py",
        "tests/test_browser_browse_handlers.py",
        "tests/test_diagnose_elevation.py",
        "tests/test_ship_status.py",
        "tests/test_browseract_parity_v4_169_34.py",
    ),
    # v4.169.35: bore tunnel runtime helpers, 141/309 survivors before the parity suite.
    # Pinned: per-OS candidate lists, exact hint texts, error classifier regexes/hints,
    # port clamp boundaries, wait seconds clamp boundaries, Popen kwargs forwarding,
    # monitor thread log capture & URL build, early process exit vs timeout contracts.
    "arena/admin/bore.py": (
        "tests/test_bore.py",
        "tests/test_bore_wiring.py",
        "tests/test_bore_route_registration.py",
        "tests/test_bore_parity_v4_169_35.py",
    ),
    # v4.169.35: agent-side filesystem helpers, 84/99 survivors before parity suite.
    # Pinned: now_iso format, safe_write atomic replacement & mode, backup_file timestamp
    # & permissions, verify_python spec/loader & syntax/runtime error, verify_bash bash -n & outputs,
    # patch_block positions (before/after/replace) & count=1 & mode preservation, patch_replace.
    "arena/agent_helpers/files.py": (
        "tests/test_arena_agent_helpers_files.py",
        "tests/test_agent_helpers_files_parity_v4_169_35.py",
    ),
    # v4.169.35: agentctl memory/recall commands, 83/110 survivors before parity suite.
    # Pinned: _arg_value, _remove_flag, mem_set validation & profile/tags, mem_get normalization
    # ('all' -> '') & truncation & missing defaults, recall_search score format & fact fallback,
    # recall_digest string vs JSON dump.
    "arena/agentctl_cli/agentctl_memory.py": (
        "tests/test_agentctl_memory.py",
        "tests/test_agentctl_memory_parity_v4_169_35.py",
    ),
    # v4.169.35: agentic handlers (react & reflect), 71/72 survivors before parity suite.
    # Pinned: auth enforcement (@authed), input JSON validation, goal missing/null handling,
    # custom vs default parameters, audit events structure, dataclass immutability (frozen=True).
    "arena/agentic/handlers.py": (
        "tests/test_agentic.py",
        "tests/test_agentic_handlers_parity_v4_169_35.py",
        "tests/test_cognitive_input_contract.py",
    ),
    # v4.165.0: the files fixed during the v4.163/v4.164 bug hunt, each
    # paired with the guard written for it. Every one is above 60%
    # covered -- below that a survivor count measures absent coverage
    # rather than weak assertions (mirror.py at 0% once produced 180
    # mutants and killed none, which said nothing about the tests).
    #
    # These run in the manual sweep (mutation-sweep.yml), not on every
    # push: `mutation_cache` keys results by content, so the gate re-runs
    # only what changed.
    "arena/mobile/apk_paths.py": (
        "tests/test_mobile_apk_upload_stays_in_staging.py",
        "tests/test_mobile_staging_root_failure.py",
        "tests/test_mobile_apk_paths_parity_v4_169_37.py",
    ),
    "arena/exec/interpreters.py": (
        "tests/test_exec_script_path_quoting.py",
        "tests/test_exec_interpreters_parity_v4_169_37.py",
    ),
    "arena/exec/client_lifecycle.py": (
        "tests/test_exec_client_disconnect_v4_169_47.py",
    ),
    "arena/exec/control_gate.py": (
        "tests/test_exec_control_gate.py",
    ),
    "scripts/update_log_timestamp.py": (
        "tests/test_inspect_update_log.py",
    ),
    "scripts/release_version_contract.py": (
        "tests/test_release_version_monotonic.py",
    ),
    "arena/autonomy/posture_identity.py": (
        "tests/test_autonomy_posture.py",
    ),
    "arena/cognitive_input.py": (
        "tests/test_cognitive_input_contract.py",
    ),
    "arena/governance/reviewer_evidence.py": (
        "tests/test_reviewer_evidence.py",
    ),
    "arena/workbench/runtime_fetch.py": (
        "tests/test_workbench_runtime_downloads.py",
        "tests/test_workbench_runtime_fetch_parity_v4_169_37.py",
    ),
    # v4.169.24: 213 survivors against 5 kills before this entry existed.
    # Two of them were live holes -- inverting the digest requirement and
    # defaulting `force` to True -- and both survived because nothing
    # called the HTTP handler at all.
    "arena/admin/handlers_update.py": (
        "tests/test_handlers_update_parity_v4_169_39.py",
        "tests/test_update_apply_guards_v4_169_24.py",
        "tests/test_handlers_update_v4_60_13.py",
        "tests/test_auto_update_diagnostics_v4_60_14.py",
        "tests/test_update_consent_binds_the_source.py",
        "tests/test_post_update_smoke_and_autostart.py",
    ),
    "arena/admin/deployment_provenance.py": (
        "tests/test_deployment_provenance.py",
    ),
    "arena/admin/deployment_tombstones.py": (
        "tests/test_update_release_tombstones.py",
    ),
    "arena/security_http.py": (
        "tests/test_security_ssrf_pinned_transport.py",
        "tests/test_security.py",
        "tests/test_security_ssrf_bypass_corpus.py",
    ),
    "arena/skills/git_source.py": (
        "tests/test_skill_git_source_policy.py",
    ),
    "arena/governance/pytest_execution_guard.py": (
        "tests/test_pytest_execution_guard.py",
    ),
    "scripts/test_import_failopen_guard.py": (
        "tests/test_import_failopen_guard.py",
    ),
    "arena/admin/auto_update_fetch.py": (
        "tests/test_auto_update_digest_required.py",
        "tests/test_auto_update.py",
        "tests/test_auto_update_fetch_parity_v4_169_36.py",
    ),
    "arena/browser/cdp_client/tabs_http.py": (
        "tests/test_cdp_websocket_url_is_loopback.py",
        "tests/test_cdp_tabs_http_parity_v4_169_36.py",
    ),
    "arena/desktop/capability.py": (
        "tests/test_windows_desktop_capability.py",
    ),
    "arena/observability/live_metrics.py": (
        "tests/test_live_metrics_rates.py",
        "tests/test_live_metrics_gpu_parse.py",
        "tests/test_live_metrics_parity_v4_169_37.py",
    ),
    "arena/mcp_client/client.py": (
        "tests/test_mcp_client_output_bounds.py",
        "tests/test_mcp_client_parity_v4_169_39.py",
    ),
    "arena/memory/recall_relevance.py": (
        "tests/test_memory_recall_relevance.py",
        "tests/test_memory_store.py",
    ),
    "arena/mobile/mirror.py": (
        "tests/test_mobile_mirror_parity_v4_169_39.py",
        "tests/test_mobile_mirror_stream_params.py",
        "tests/test_mobile_mirror_pipeline_lifecycle.py",
    ),
}


def _run_one(source: str, tests: tuple[str, ...]) -> tuple[int, int]:
    """Return (survived, total). Fails closed on any tooling problem."""
    existing = [t for t in tests if (ROOT / t).exists()]
    missing = [t for t in tests if not (ROOT / t).exists()]
    if missing:
        raise SystemExit(f"FAIL-CLOSED: guarding tests missing for {source}: {missing}")

    CACHE.unlink(missing_ok=True)
    runner = "python3 -m pytest -x -q -o addopts=\"\" -p no:randomly " + " ".join(existing)
    proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
        ["mutmut", "run", "--paths-to-mutate", source,
         "--runner", runner, "--no-progress"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800,
    )
    if not CACHE.exists():
        sys.stderr.write((proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:])
        raise SystemExit(f"FAIL-CLOSED: mutmut produced no results for {source}")

    con = sqlite3.connect(CACHE)
    try:
        counts = dict(con.execute(
            "select status, count(*) from Mutant group by status").fetchall())
    finally:
        con.close()

    survived = int(counts.get("bad_survived", 0))
    killed = int(counts.get("ok_killed", 0))
    total = sum(int(v) for v in counts.values())
    if total == 0:
        raise SystemExit(f"FAIL-CLOSED: zero mutants generated for {source}")
    if killed == 0:
        raise SystemExit(
            f"FAIL-CLOSED: nothing was killed in {source}. The listed tests "
            "probably do not exercise this file, which makes the survival "
            "count meaningless rather than alarming.")
    return survived, total


def _list_survivors() -> None:
    if not CACHE.exists():
        raise SystemExit("no .mutmut-cache; run the gate first")
    con = sqlite3.connect(CACHE)
    rows = con.execute(
        "select m.id, l.line_number, l.line from Mutant m "
        "join Line l on m.line = l.id where m.status='bad_survived' "
        "order by l.line_number").fetchall()
    con.close()
    print(f"{len(rows)} surviving mutants (inspect one with: mutmut show <id>)")
    for mid, lineno, line in rows:
        print(f"  #{mid:<5} L{lineno:<5} {(line or '').strip()[:88]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        _list_survivors()
        return 0

    if shutil.which("mutmut") is None:
        # Optional dependency: skipping is honest, silently passing is not.
        print("SKIP: mutmut is not installed (pip install mutmut==2.5.1)")
        return 1 if args.write_baseline else 0

    results: dict[str, int] = {}
    for source, tests in TARGETS.items():
        if not (ROOT / source).exists():
            raise SystemExit(f"FAIL-CLOSED: target {source} does not exist")

        # v4.163.0: skip work that would re-prove an unchanged result.
        # The key covers the source, its guarding tests AND the mutmut
        # version, because a change to any of the three can change the
        # verdict. A miss always means "run it" -- never "assume fine" --
        # and a hit is still checked against the baseline below, so the
        # cache can save time but cannot lower the bar.
        cached = None if args.write_baseline else mutation_cache.lookup(source, tests)
        if cached is not None:
            survived, total = int(cached["survived"]), int(cached["total"])
            print(f"  {source:38s} survived {survived:4d} / {total}  (cached)")
        else:
            survived, total = _run_one(source, tests)
            mutation_cache.record(source, tests, survived=survived, total=total)
            print(f"  {source:38s} survived {survived:4d} / {total}")
        results[source] = survived

    if args.write_baseline:
        BASELINE.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
        print(f"baseline written: {BASELINE.relative_to(ROOT)}")
        return 0

    if not BASELINE.exists():
        raise SystemExit("FAIL-CLOSED: no baseline; run --write-baseline and "
                         "review the number before committing it")
    floor = json.loads(BASELINE.read_text(encoding="utf-8"))

    grew = {k: (floor.get(k, 0), v) for k, v in results.items() if v > floor.get(k, 0)}
    if grew:
        print("\nMUTATION DEBT GREW (ratchet blocks this):")
        for k, (was, now) in sorted(grew.items()):
            print(f"  {k}: {was} -> {now} (+{now - was})")
        print("\nA new surviving mutant means the tests cannot distinguish your "
              "code from a broken version of it.\n"
              "Inspect with: python scripts/mutation_gate.py --list")
        return 1

    for k, v in sorted(results.items()):
        if k in floor and v < floor[k]:
            print(f"  improved: {k} {floor[k]} -> {v}; lower the floor with "
                  "--write-baseline")
    print("OK: surviving mutants at/below baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
