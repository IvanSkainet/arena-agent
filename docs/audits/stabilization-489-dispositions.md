# T73 / #489 — integration scope and PR dispositions

This is an implementation/disposition ledger, **not final merge acceptance**.
Exact-head hosted CI, assembled review and post-merge verification remain exit
conditions. Historical green runs must not be presented as validation of a
later source revision.

## Original ten open candidates

| PR | Disposition in the integration |
| --- | --- |
| #470 | Integrate remote smoke token-path examples and documentation regression tests. |
| #468 | Integrate orphan reclamation; additionally bind subprocess lifetime to the owner and test actual owner death/timeout with child and grandchild. |
| #467 | Integrate incremental JSONL imports; preserve transactional checkpointing, rotation/rewrite detection and process serialization tests. |
| #466 | Integrate corrupt SQLite quarantine/rebuild; distinguish corruption from ordinary operational failures. Persistent recovery status is visible in public health and doctor, without public quarantine paths. |
| #465 | Integrate centralized state/code/workspace resolution, preserving legacy state, explicit choices, token/config fallback, packaged CLI dispatch, write protections and watcher confinement. Review fixes are part of the integration rather than a blind cherry-pick. |
| #391 | Already superseded by the existing guarddog dependency state; closed as obsolete, not reapplied. |
| #390 | Reviewed and closed without integration: intermediate Codecov 7.1.0 update is already behind 7.1.1 and does not fix an established stabilization defect. Keep the existing immutable pin; do not claim the proposed version was installed. |
| #388 | Integrate a detached cache for the two fixed home-walking probes, with complete results and worker ownership/lease tests. Do not replace it with silent truncated discovery. |
| #360 | Already superseded by the existing harden-runner pin; closed as obsolete. |
| #359 | Reviewed and closed without integration: intermediate TruffleHog 3.97.4 update is behind 3.99.9. Do not blindly revive an old detector/transport-policy diff. The pinned secret scanner and zero-secret gate remain required. |

Functional source PRs are to be closed as superseded **after** the assembled
integration merges, not treated as merged independently.

## All 27 historical closed-without-merge candidates

A closed PR is not automatically an unfinished requirement. Compare its intended
invariant with the current implementation and tests before reviving anything.

| PR(s) | Disposition / current acceptance surface |
| --- | --- |
| #265 | Generated cubic wiki snapshot, not authoritative runtime implementation. Do not restore a stale managed documentation tree. |
| #389 | Superseded alternative to #388: a two-second truncated crawl is not the selected complete-result background-cache contract. |
| #312 | Superseded CodeQL upload action proposal; current action/runtime manifest already records the replacement pin. |
| #310, #301 | Duplicate SBOM-action updates superseded by the existing pinned action/runtime manifest. |
| #309 | Setup-Java update already represented in the existing pinned action/runtime manifest. |
| #306 | Obsolete tarsafe bump; package safety and extraction behavior were handled in the preceding stabilization integration (#475). Do not reapply old dependency resolution. |
| #305 | Historical disposable-email-domains bump, not a remaining runtime defect; do not revive a closed ecosystem update mechanically. |
| #304, #303 | Historical botocore/boto3 bumps, not independent unfinished stabilization requirements. |
| #302 | Autoclosed scan-action proposal superseded by the pinned action/runtime manifest. |
| #262 | Renovate onboarding proposal was intentionally not adopted; do not add a second dependency-update policy as a stabilization side effect. |
| #289 | Superseded by #287 and current unusable-command/path validation; retain `test_exec_nul_cmd_288.py` and `test_unexpandable_path_290.py`. |
| #275 | Superseded by #279/current required API fuzz gate, not an omitted gate to reinstall. |
| #168 | Obsolete grouped dependency update; use the current hashlocked dependency state, not a historical resolver output. |
| #143, #147 | Superseded by #146 and subsequent subprocess/text hardening; browser CLI UTF-8 output and parent decoding remain covered by focused UTF-8 tests. |
| #121 | Superseded by #123/#131 and current browser navigation policy; do not resurrect the earlier overlapping implementation. |
| #72 | Cosmetic generated CodeFactor CSS/comment changes, not confirmed missing functional/security fixes. No wholesale restoration of old generated dashboard/extension assets. |
| #73 | Explicit **NEVER MERGE** reviewer shadow benchmark. Remains excluded. |
| #69 | Superseded by #70/current execution-control environment policy; retain the broader Windows/POSIX environment-control tests. |
| #66 | Superseded by #157/current total, constant-time token comparison; do not reintroduce the narrower earlier comparison. |
| #21 | Required effects are already present: release tracked-mode/symlink refusal, source-bound attestation and checksum documentation/tests. Do not resurrect a stacked auto-fix PR. |
| #6 | Obsolete mypy ecosystem bump; not a reason to replace the present analyzer toolchain. |
| #1 | Historical aiohttp advisory proposal superseded by the current hashlocked runtime/CI dependency set and vulnerability checks. |
| #5, #4 | Historical grouped dependency resolver outputs, superseded by later dependency maintenance. |

## Stabilization invariants beyond those PRs

- #407: lock regeneration follows constraint dependencies; co-installed lock
  conflicts are checked before accepting regenerated files.
- Dependency graph: constraints projected by Dependabot must remain available;
  use the CI `.txt` lock with the same pins/hashes, not an unsupported vanished
  `.lock` constraint. Local projection tests are not a hosted-graph verdict.
- #408: CPU sampling must not block the shared event loop.
- #410: README metrics tests must never rewrite either committed README.
- #411/#414: readiness and doctor summaries must reflect critical and optional
  failures, rather than constant health or counting failed checks as passed.
- #463: recovery must preserve original corrupt bytes and expose persistent,
  redacted degradation after restart, not silently imply restored facts.
- State remains distinct from executable code and the allowed workspace. This
  is not a promise to implement every proposed CLI/XDG/banner redesign in #430.
  Do not close that broader product-design proposal merely because its underlying
  state-placement defects have fixes.
- Issue #31 and unselected future product features remain outside T73.

## Owner-approved external-game policy

The owner explicitly made the Book of Eternity contract optional. It is an
independent manual/weekly diagnostic, with no PR/push trigger and no dependency
from release attestation. Upstream drift is informational; actual compatibility
failures remain visible and upload available evidence. The unvalidated latest
upstream pin was not adopted. Local Arena relay/security tests stay required.
No game readiness, security guard or failed test is forced green to satisfy this
policy. Coordination with the external game's owner is not a T73 prerequisite.

### Legacy task ownership safety

Automatic orphan recovery requires a recorded owner PID (and compares its
creation identity when available). PID-less legacy/partially claimed records
are retained even past their timeout: an old runner cannot participate in a
new lock protocol and could still finalize success. This deliberately avoids
publishing a contradictory `failed/interrupted` result. Stop old runners and
inspect/archive such records manually; a deadline alone is not proof of death.
The recovery API retains `grace_seconds` for caller compatibility, not as a
permission to steal unidentifiable work. The regression simulates late legacy
success after a sweep and verifies there is no conflicting failed result.
