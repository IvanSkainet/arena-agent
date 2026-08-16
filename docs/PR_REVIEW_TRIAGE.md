# Pull Request Review Triage

<!-- pr-review-surfaces: review-threads,submitted-reviews,ordinary-pr-comments,check-rollup -->
<!-- pr-review-dispositions: accepted,partially-accepted,rejected,duplicate,follow-up,noise -->
<!-- pr-review-apps: keep=coderabbit,qodo,sonarqube-cloud,codacy,sourcery,codefactor;pending=deepsource;codefactor-probation=10-prs;exact-head-required -->

Automated review is evidence, not authority. A green check does not prove the
change works, and a bot-authored patch does not become correct because another
bot approved it.

This procedure applies to every non-trivial pull request. Release, security,
workflow, protocol, and cross-repository changes require every available
configured reviewer surface to be read, but quota-skipped/unavailable Apps are
recorded as no signal rather than treated as blockers. A manual CodeRabbit or
Qodo review is preferred for high-risk changes when its independent quota is
available.

## Current reviewer roles

| Integration | Role | Merge status |
|---|---|---|
| CodeRabbit | Manually triggered semantic review for high-risk changes; benchmark strength was exact DNS-rebinding analysis. | Informational; one-review rolling quota observed. Never merge autofixes without re-deriving and testing the invariant. |
| Qodo | Independent semantic/cross-file review. Benchmark found insecure TLS and a cross-file release-packaging concern. | Informational trial; automatic commits/autofix remain disabled and every finding is revalidated. |
| SonarQube Cloud | Whole-tree and PR-delta static analysis with low content permission. | Informational; legacy baseline and PR Quality Gate are not required until rule-level precision is measured. |
| Codacy | Multi-analyzer static analysis and independent quota. | Informational/manual disposition; duplicate annotations are collapsed by root location before counting. |
| Sourcery | Automatic maintainability/test-completeness review when quota exists. | Informational; exact-head rate-limit reviews count as no signal. |
| DeepSource | Historical signal exists, but current analyses are quota-skipped and the vendor dashboard is Cloudflare-blocked for the owner. | Keep pending vendor response; skipped checks are no signal. |
| CodeFactor | Fast independent static quota; benchmark recall was low with one control false positive and high App permission cost. | Informational 10-real-PR probation; remove if it adds no unique accepted finding. |

Functional overlap is allowed because independent quotas improve availability.
Every App must still justify its false-positive, permission, cost, and failure-mode
budget. The measured baseline and decisions are in
[`reviewer-benchmark-67.md`](audits/reviewer-benchmark-67.md).

## Read every GitHub review surface

For the exact current head SHA, inspect all of the following:

1. **Review threads** — inline findings and their `isResolved` state.
2. **Submitted reviews** — the top-level review body; Sourcery often places its
   only substantive feedback here without creating a thread.
3. **Ordinary PR comments** — review guides, generated-fix reports, and bot
   follow-up messages are issue comments, not reviews.
4. **Check rollup** — verify the App check belongs to the exact head SHA and
   distinguish `success`, `failure`, and `skipped`.

Reading only unresolved threads is insufficient. That method found
CodeRabbit's four inline findings on PR #20 but initially missed Sourcery's
high-level review.

## Classify each finding

Record one disposition for every substantive finding:

- **accepted** — the finding is valid and fixed in the owned branch;
- **partially accepted** — the risk is valid, but the suggested implementation
  would weaken another invariant or uses unsupported semantics;
- **rejected** — concrete repository evidence disproves the finding;
- **duplicate** — another finding already covers the same root cause;
- **follow-up** — valid but out of the linked Issue's scope; open a narrow Issue
  before merge;
- **noise** — style, marketing, or generated prose with no engineering action.

A rejected suggestion still needs a short technical reason. Examples from the
measured sample:

- Relaxing exact CI job-set assertions was rejected because those assertions
  deliberately make ungoverned jobs visible.
- Sharing executable constants between the release packer and verifier was not
  accepted because a verifier that imports producer policy can repeat the same
  defect. A declarative shared specification is only acceptable if independent
  sabotage still detects producer/checker disagreement.

## Validate before resolving

For accepted findings:

1. Reproduce the defect or demonstrate the missing contract.
2. Implement the root-cause fix on the Issue branch.
3. Add focused regression and bilateral sabotage coverage.
4. Run focused checks, full preflight, and applicable security checks.
5. Push and verify all checks against the exact new head SHA.
6. Reply with the commit and evidence.
7. Resolve the thread only after the evidence exists.

Top-level review feedback has no resolvable thread. Add a PR comment recording
its disposition so it is not silently ignored.

## Generated autofix branches

Generated patches are untrusted review data:

- inspect every changed file and every omitted file;
- verify that proposed CLI flags and API fields exist in the pinned/current
  official interface;
- do not merge a stacked bot PR into the owned branch;
- reimplement the validated invariant on the linked Issue branch;
- close the generated PR as superseded once equivalent or stronger evidence is
  present.

PR #21 is the reference case: CodeRabbit correctly identified release defects,
but its generated branch could not update the workflow and required a stronger
exact-SHA candidate-manifest implementation. Sourcery's review of that branch
was still useful independent evidence.

## Merge record

Before merge, record:

- linked Issue and current head SHA;
- accepted/rejected/follow-up dispositions;
- unresolved-thread count;
- required checks for that exact head;
- live evidence when the change affects a real external boundary.

AI checks remain informational. Branch rules, deterministic tests, security
checks, and live acceptance remain the merge authority.
