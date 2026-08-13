## Tracked task

Closes #

Task Board ID: T

## Root cause and invariant

<!-- State the root cause. Name the invariant this change restores. Do not describe only the symptom. -->

## Scope and non-goals

<!-- List affected modules/repositories and explicit boundaries. -->

## Verification

- [ ] Focused tests pass.
- [ ] Bilateral sabotage: the intentionally broken implementation makes the new/changed gate fail.
- [ ] Healthy implementation passes after restoration.
- [ ] `python scripts/preflight.py` passes.
- [ ] Applicable lint/type/dead-code ratchets remain at zero.
- [ ] Applicable security gates pass without new unexplained suppressions.

Commands and results:

```text
<exact bounded commands and outcomes>
```

## Live E2E evidence

<!-- Name the real artifact, platform, transport chain, observation, and recovery. If not applicable, explain why. -->

## Security and release impact

- Security impact:
- Permissions or credential impact:
- Release artifact impact:
- Rollback/recovery plan:

## Cross-repository impact

<!-- Link upstream/downstream Issues and PRs. Record compatibility commits. Use "None" only after checking. -->

## Checklist

- [ ] No credentials, private tunnel URLs, runtime state, or unbounded logs are included.
- [ ] Official output JSON shapes have no unknown top-level fields.
- [ ] Documentation/examples changed with the public or agent-facing contract.
- [ ] All automated review surfaces were triaged for the exact head SHA; dispositions follow [`docs/PR_REVIEW_TRIAGE.md`](https://github.com/IvanSkainet/arena-agent/blob/HEAD/docs/PR_REVIEW_TRIAGE.md).
- [ ] The PR remains one coherent change; unrelated findings have their own tracked Issues.
