#!/usr/bin/env bash
# Push master and the v* tags of this checkout to the GitLab mirror.
#
# Called by .github/workflows/gitlab-mirror.yml. Reads the deploy key from
# GITLAB_MIRROR_SSH_KEY. MIRROR_URL and MIRROR_KNOWN_HOSTS exist so that a
# test can aim the script at a local repository.
set -euo pipefail

MIRROR_URL="${MIRROR_URL:-git@gitlab.com:IvanSkainet/arena-agent.git}"

# gitlab.com's ED25519 host key, as published at
# https://docs.gitlab.com/user/gitlab_com/#ssh-known_hosts-entries
# (SHA256:eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8). Pinned here and not
# fetched with ssh-keyscan: a scanned key is whatever the network answers.
GITLAB_HOST_KEY="gitlab.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAfuCHKVTjquxvt6CM6tdG4SLp1Btn/nOeHHE5UOzRdf"

if [ -z "${GITLAB_MIRROR_SSH_KEY:-}" ]; then
  echo "GITLAB_MIRROR_SSH_KEY is empty: the repository secret is missing, so nothing was pushed." >&2
  exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
umask 077
printf '%s\n' "$GITLAB_MIRROR_SSH_KEY" > "$workdir/key"
printf '%s\n' "$GITLAB_HOST_KEY" > "$workdir/known_hosts"

export GIT_SSH_COMMAND="ssh -i $workdir/key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${MIRROR_KNOWN_HOSTS:-$workdir/known_hosts}"

# No --force and no --prune: the mirror only ever moves forward.
git push "$MIRROR_URL" "HEAD:refs/heads/master" "refs/tags/v*:refs/tags/v*"

echo "GitLab master is now $(git rev-parse HEAD)."
