#!/usr/bin/env bash
# sync_superpowers_from_upstream.sh — refresh skills/superpowers/ from upstream.
#
# We ship a single vendored copy of obra/superpowers at skills/superpowers/
# (see docs/SUPERPOWERS.md). This script keeps it in sync with the upstream
# main branch. Preserves any repo-local metadata files we do not want to
# clobber (.gitattributes/.gitignore intentionally left alone).
#
# Modes:
#   --check   Show a diff summary but do not touch anything (default)
#   --apply   Actually rsync upstream into skills/superpowers/
#   --branch NAME  Track a different upstream branch (default: main)
#   --url URL      Override the upstream repository URL
#   -h|--help
set -euo pipefail

UPSTREAM_URL="https://github.com/obra/superpowers.git"
UPSTREAM_BRANCH="main"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="skills/superpowers"
MODE="check"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)  MODE="check"; shift ;;
    --apply)  MODE="apply"; shift ;;
    --branch) UPSTREAM_BRANCH="$2"; shift 2 ;;
    --url)    UPSTREAM_URL="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v git   >/dev/null 2>&1 || { echo "git required" >&2; exit 2; }
command -v rsync >/dev/null 2>&1 || { echo "rsync required" >&2; exit 2; }

FULL_TARGET="$REPO_ROOT/$TARGET"
if [[ ! -d "$FULL_TARGET" ]]; then
  echo "Target does not exist: $FULL_TARGET" >&2
  exit 2
fi

SCRATCH="$(mktemp -d -t superpowers-sync-XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT

echo ">> Cloning $UPSTREAM_URL ($UPSTREAM_BRANCH) ..."
git clone --depth 1 --branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$SCRATCH/upstream" >/dev/null 2>&1

UPSTREAM_REV="$(git -C "$SCRATCH/upstream" rev-parse --short HEAD)"
echo ">> Upstream at $UPSTREAM_REV"

echo
echo ">> Diff summary ($MODE mode) for $TARGET"
DIFF_OUT="$(diff -qr "$SCRATCH/upstream" "$FULL_TARGET" 2>/dev/null || true)"
if [[ -z "$DIFF_OUT" ]]; then
  echo "   No differences. $TARGET is at upstream $UPSTREAM_REV."
  exit 0
fi
echo "$DIFF_OUT" | sed 's/^/   /'

if [[ "$MODE" != "apply" ]]; then
  echo
  echo ">> Re-run with --apply to write changes."
  exit 0
fi

# We preserve repo-management files so downstream policies stay intact.
EXCLUDES=(
  --exclude='.git'
  --exclude='node_modules'
)

echo
echo ">> rsync --delete-after ..."
rsync -a --delete-after "${EXCLUDES[@]}" "$SCRATCH/upstream"/ "$FULL_TARGET"/
echo ">> Done. Review with: git -C $REPO_ROOT diff -- $TARGET"
echo ">> Upstream rev: $UPSTREAM_REV"
