# Release 4.170.2 follow-up (#491)

## Draft-signing fix

Signing run 44590187961 matched exact-source candidate bytes and verified
provenance/SPDX, signed locally and verified, then failed because the REST
release-by-tag endpoint returned 404 for draft 451763650. `gh release view`
resolved the draft correctly. Resolve a numeric ID with the CLI, then fetch
release flags by ID. Bad/empty IDs fail closed. Two different valid IDs are
covered by executable regression tests. All existing verification remains.

Same-tag signing is serialized without cancellation, and every attached remote
signature/certificate pair is verified. A partial set must not pass just because
one `.sig` exists. Concurrency does not claim to prevent an unrelated human from
publishing a draft: RELEASE.md still requires successful signing before publish.
An early external publication fails closed rather than producing a false pass.

## Relock tool advisories and unpublished tag

Dependabot 26 (GHSA-2cv4-cqwr-gwf7) and 27 (GHSA-hq85-5cpj-mr62) affect
uv 0.12.7. Both are patched by 0.13.4. The relock-tool input and universal
hashlock are updated; all 19 release hashes match PyPI metadata. Runtime
requirements are unchanged. Neither alert was dismissed. The PR-scoped alert
gate must prove the changed manifest is fixed; after merge the default-branch
alerts must close before release.

The old v4.170.1 draft was deleted before publication. Repository rules refused
to delete the protected tag (HTTP 422); it remains pinned and will not be
rewritten or used for publication. New source-bound candidate artifacts and
Windows ZIP acceptance are required for v4.170.2.

## Existing CodeQL dismissal recorded, not silently expanded

The dismissal ledger was one behind live CodeQL: rule py/path-injection had
34 dismissed alerts, but only 33 recorded. The one additional disposition is
alert 643, `arena/files/sandbox.py`, previously dismissed as false positive
during PR490. No new alert is dismissed here. The per-rule count rises by
exactly one, false-positive count 16 to 17; all other counts are unchanged.

Its recorded rationale is that `expanduser` constructs a path; subsequent
`resolve_home_path` resolution and jail-root containment decide access before
filesystem use, rejecting escape with 403. PR490 boundary regressions covered
traversal/symlinks and malformed paths. The current sink and boundary are
reviewed again for this ledger entry. This records the existing decision in
the repository as the dismissal gate explicitly requires; it does not relax
scan severity, permissions, required checks or any runtime boundary.

## Explicitly approved withdrawal accounting correction

The operator approved an evidence-checked exception for the unpublished,
withdrawn intermediate patch v4.170.1. The non-strict limit remains one active
unpublished patch; strict mode still requires the active version to be published.
No required check, tag protection or severity threshold is removed.

The checked-in withdrawal ledger pins the annotated tag object, source commit,
deleted draft ID and failed signing run. Before deducting one intermediate patch,
CI verifies those immutable identities against GitHub, confirms the failed signer
belongs to this repository/source/workflow, verifies the recorded draft is gone,
and enumerates releases (including visible drafts) to reject a recreated release.
Malformed/missing evidence and network failures during verification fail closed.
Only intermediate patches in the same minor line can count: neither the active
version nor a published predecessor nor a cross-minor gap receives credit.
Duplicate ledger tags are rejected; real remaining debt above one still fails.
The version-sync job receives only actions:read to verify historical signer data.

Live owner-API validation: non-strict passes for 4.170.2 above published 4.170.0
with the verified 4.170.1 withdrawal; --strict still fails until publication.
Targeted withdrawal/release-gap/version/signing/JSON-contract suites pass.
