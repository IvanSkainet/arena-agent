# Pull Request Review Triage

Automated review is evidence, not authority. A green check does not prove the
change works, and a bot-authored patch does not become correct because another
bot approved it.

This procedure applies to every non-trivial pull request. Release, security,
workflow, protocol, and cross-repository changes require both CodeRabbit and
Sourcery evidence before merge.

## Current reviewer roles

| Integration | Role | Merge status |
|---|---|---|
| CodeRabbit | Manually triggered independent review for high-risk changes; strongest observed signal is cross-file security and release invariants. | Informational; never merge autofixes without re-deriving and testing the invariant. |
| Sourcery | Automatic second review; strongest observed signal is missing tests, brittle assertions, maintainability, and documentation consistency. | Informational; summary feedback must be triaged even when it creates no review thread. |
| DeepSource | Analysis quota exhausted; recent PR and `master` checks are skipped. Existing scanners already cover its static-analysis and secret-scanning classes. | Remove the GitHub App installation; do not treat a skipped check as evidence. |

Do not add another AI reviewer until CodeRabbit and Sourcery have a classified
sample of at least ten representative PRs. Functional overlap alone is not a
reason to remove a reviewer, but every additional App must demonstrate a new
signal that exceeds its false-positive and permission costs.

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
