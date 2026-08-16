# T52 Marketplace Reviewer Benchmark — Issue #67

Date: 2026-08-16
Infrastructure commit: `af33783c18133d5ddd112719f096b19cad584cb9`
Never-merged benchmark PR: [#73](https://github.com/IvanSkainet/arena-agent/pull/73)
Final benchmark head: `c976b83bd170d2666a33f412fe96ba31644d5118`

## Method

PR #73 contained seven synthetic, non-executed defect classes and four benign
controls. It was explicitly titled `NEVER MERGE`, carried no real credentials or
live exploit payloads, and was closed without merge after collection.

The exact-head collector added in PR #71 read submitted reviews, inline comments,
ordinary comments, and check runs separately. Reviews/comments carrying a commit
ID were classified as exact or stale. Ordinary comments remained unbound. A head
change, wrong expected SHA, pagination, malformed member, duplicate check, or
truncated check count failed closed.

The corpus covered:

- insecure-by-default TLS;
- shallow nested scanner-report validation;
- permissive source/release version parsing;
- parent-only subprocess termination;
- DNS rebinding between validation and connection;
- last-global-subprocess-call assertions;
- stale security-preset metadata.

Controls covered fixed argv without a shell, intentional scaffold TODO text,
explicit operator insecure-TLS opt-out, and documented facade/re-export behavior.

## Exact-head hosted results

| Tool | Ran | Exact defect recall | Other/context signal | Control/noise | Availability |
|---|---:|---:|---|---|---|
| CodeRabbit | yes | 1/7 (`DNS rebinding`) | partial hard-kill and last-call observations | no benign-control finding | one review per rolling hour; manual trigger |
| Qodo | yes | 1/7 (`TLS default`) | release-packaging hypothetical and two suppression-policy findings | explicit TLS opt-out not flagged | worked after onboarding and manual `/review`; 14-day trial |
| CodeFactor | yes | 1/7 (`TLS default`) | none | explicit TLS opt-out flagged | automatic, about one second |
| SonarQube Cloud | yes | 0/7 | none on intended defects | explicit TLS opt-out was the only PR issue; New Code Security Rating D | automatic |
| Codacy | yes | 2/7 unique (`TLS`, generic URL/SSRF surface) | multiple bundled-analyzer duplicates | 4 unique noise/control locations, 9/15 raw annotations | automatic, manual disposition at aggressive profile |
| Sourcery | skipped | 0/7 | old guide described files but exact review was quota message | stale/unbound evidence remained visible | weekly diff quota exhausted |
| DeepSource | skipped | 0/7 | none | none | analysis quota exhausted; vendor dashboard blocked by Cloudflare |

### CodeRabbit

CodeRabbit found the DNS validation/connection split and default redirect behavior,
which was the most exact semantic security finding in the benchmark. It noticed
`process.kill()` but discussed graceful shutdown rather than the full child-tree
invariant. It also reported empty-list behavior around `captured[-1]`, adjacent
to but different from the intended global-call overwrite defect.

### Qodo

Qodo caught insecure-by-default TLS and performed useful cross-file inspection of
release packaging. The latter was correct only under a hypothetical merge; the PR
contract explicitly prohibited merge. Two more findings concerned suppression
rationales. Qodo respected the explicit insecure operator opt-out control.

### CodeFactor

CodeFactor emitted two annotations for the first Python head: one valid TLS
finding and one identical finding on the explicit insecure opt-out control. It
was fast but low-recall and requested broad repository permissions.

### SonarQube Cloud

The PR delta contained exactly one Sonar issue: `python:S4423` on the explicit
operator opt-out. Sonar missed the insecure default on line 16 and every other
corpus defect. The Quality Gate therefore failed from a control false positive.

The project-wide numbers are legacy baseline, not PR signal:

- 3,011 total issues;
- 2,727 code smells;
- 164 bugs;
- 120 vulnerabilities;
- 46 blockers.

The 46 blocker labels split into 19 path-construction findings, 14 JavaScript
implicit-global findings, 9 always-same-return maintainability findings, 2
command-construction findings, 1 reflected-input finding, and 1 invalid-CSS-unit
finding. They require independent reproduction and are not 46 confirmed security
vulnerabilities.

### Codacy

Codacy emitted 15 raw annotations. Four analyzers repeated the valid TLS issue;
two repeated the dynamic `urllib`/file-scheme surface. Noise included two warnings
for importing `subprocess`, a false question about `is_private` being callable,
two findings on the fixed `git --version` argv control, and four repeats on the
explicit TLS opt-out.

The 39,442 project-wide issues are dominated by profile/coverage mismatch:

- 10,536 broad Python security-pattern findings;
- 10,333 assert-statement findings;
- 5,390 additional non-test-assert findings;
- 4,863 PEP 257 documentation findings;
- 1,379 Pyright findings.

Those five groups account for over 80% of the total and must not be bulk-fixed.

## Local/no-key results

| Tool | Corpus result | Noise / applicability | Runtime |
|---|---|---|---:|
| Skylos 4.33.2 | 2/7 (`TLS`, generic SSRF) | duplicate TLS rules, explicit opt-out FP, unused fixture noise | 185 s; 59 MB JSON |
| Fallow 3.16.0 | 0/7 | one unused JS fixture; Node 20 compatibility and missing-node_modules warnings | ~0.5 s |
| AgentShield 1.4.0 | not applicable to corpus | 15 MCP-policy findings; useful only as separate MCP configuration audit | ~5 s |
| Harness Score 1.6.0 | not a defect reviewer | reported L1/58 and detected no Arena harness despite CI/tests/skills | ~1 s |

## Effective GitHub App permission cost

| App | Notable effective permissions |
|---|---|
| SonarQube Cloud | contents read; checks/statuses/pull_requests/security_events write |
| Codacy | contents read; checks/statuses/issues/pull_requests write; repository and organization hooks write |
| Qodo | contents/issues/pull_requests/discussions write; actions/checks read |
| CodeRabbit | contents/issues/pull_requests/checks/statuses write; actions read |
| CodeFactor | contents/issues/pull_requests/repository-hooks write; administration and organization-administration read |
| DeepSource | contents/pull_requests/checks/statuses write; administration and hooks read |
| Sourcery | contents/issues/pull_requests/checks/statuses/actions/workflows write |

Broad write access is not unique to one vendor. Keep/remove decisions must price
permissions consistently against unique signal and independent quota.

## Decisions

1. No hosted reviewer becomes a required check. Vendor quota/network failure must
   not block repository governance.
2. Keep CodeRabbit as manual high-risk semantic review while quota permits.
3. Keep Qodo through its trial as an independent semantic/quota lane; disable or
   refuse automatic commits/autofix.
4. Keep SonarQube Cloud and Codacy informational while their legacy baselines are
   sampled by rule. Do not bulk-fix issue counts or use them as required gates.
5. Keep DeepSource installed pending the vendor response; it remains unavailable
   evidence, not a green result.
6. Keep Sourcery informational; exact-head rate-limit reviews count as no signal.
7. CodeFactor has low unique recall, one control false positive, and high permission
   cost, but it is a fast independent quota lane. Keep it informational for a
   probationary 10-real-PR sample; remove it if that sample adds no unique accepted
   finding.
8. Do not add Fallow, AgentShield, or Harness Score as PR reviewers. Retain Skylos
   only as a possible bounded one-shot audit, not permanent CI, until noise and
   output size are reduced.
9. Evaluate any third-wave AI reviewer (for example Gitar) only in review-only
   mode, with automatic commits/healing disabled and permissions recorded first.

## Gate evidence

The collector's mutation target finished at 0/217 surviving mutants. A sabotage
that classified every bound review as exact made the stale-surface contract red.
Live collection rejected an intentionally stale expected SHA for PR #70, then
reported the current head as exact=0, stale=2, unbound=3. PR #73 later produced
exact Qodo and CodeRabbit evidence while preserving stale Sourcery evidence.
