# README metrics refresh

Code metrics and traffic are different generated blocks. Code/file counts come
from `scripts/render_readme_metrics.py`. Traffic comes from the authenticated
GitHub clones API, not release downloads. Unique cloners can include automation;
neither clones nor downloads establishes a number of human users.

## Credential

Create a fine-grained PAT scoped only to this repository with:

- Administration: read (GitHub traffic API).
- Contents: read/write (the refresh branch, not a protection bypass).
- Pull requests: read/write (open the generated update for normal checks).

Store it as the Actions secret `README_TRAFFIC_TOKEN`, with an expiry and a
rotation reminder. Never reuse secret-scanning or Android-signing credentials.
The default job token has only contents:read; checkout does not persist it.
The PAT is passed only to the trusted refresh step. Git uses an checked-in executable
askpass helper containing no credential material: the token is not in remote URLs, command arguments, or git config.

## Operation

Only master dispatches can enter the credential-bearing job. Checkout is pinned
to the event SHA. The daily/manual `traffic badge` workflow invokes `scripts/refresh_readme_pr.py`.
It fetches master, regenerates both blocks, pushes only
`automation/readme-metrics-<unique-id>` without force, and opens a regular PR to master.
PAT-created PR events run the normal CI/review pipeline. The job never merges,
enables bypass, changes a ruleset, or pushes to master. If a refresh PR is already
open, it retains that commit rather than repeatedly invalidating review. Its
snapshot date stays visible until the PR actually merges; proposals are not
claimed as daily merged updates. Fresh unique branch names avoid collisions with retained squash/rebase-merged
or orphaned branch tips. No remote branch is force-pushed or deleted.

Missing credentials, API errors and malformed counts fail rather than becoming
zero-valued metrics. Failed refreshes leave the last dated snapshot visible.
`render_traffic_badge.py --write` writes locally only; publishing is a separate
step. To regenerate local code metrics, use `python scripts/render_readme_metrics.py`.

The prior workflow failed with HTTP403 using GITHUB_TOKEN. The historical README
traffic figures retain their original measurement date in the infrastructure PR;
new figures must come from a successful authenticated refresh, not a hand edit.
