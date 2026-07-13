#!/usr/bin/env bash
# sync_superpowers_from_upstream.sh — refresh vendored copies from obra/superpowers.
#
# Modes:
#   --check           Show diff summary only (default)
#   --apply           Actually rsync into the target
#   --into PATH       Target dir (default: tools/superpowers)
#   --skills-only     Only sync the skills/ subdirectory (safer for Arena fork)
#
# The script clones upstream into a temp dir, then rsyncs. Local
# .gitattributes and .gitignore are preserved. When targeting the Arena
# fork (skills/superpowers/skills/) --skills-only is enforced.
set -euo pipefail

UPSTREAM_URL="https://github.com/obra/superpowers.git"
UPSTREAM_BRANCH="main"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="tools/superpowers"
MODE="check"
SKILLS_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)        MODE="check"; shift ;;
    --apply)        MODE="apply"; shift ;;
    --into)         TARGET="$2"; shift 2 ;;
    --skills-only)  SKILLS_ONLY=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Safety: never overwrite the whole Arena fork wholesale.
case "$TARGET" in
  skills/superpowers*|*/skills/superpowers*)
    if [[ $SKILLS_ONLY -eq 0 ]]; then
      echo "!! Refusing to sync entire Arena fork ($TARGET) without --skills-only." >&2
      echo "   Arena fork carries hand-tuned SKILL.md text; run:" >&2
      echo "     $0 --into $TARGET --skills-only [--apply]" >&2
      exit 3
    fi
    ;;
esac

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync required" >&2; exit 2
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git required" >&2; exit 2
fi

FULL_TARGET="$REPO_ROOT/$TARGET"
if [[ ! -d "$FULL_TARGET" ]]; then
  echo "Target does not exist: $FULL_TARGET" >&2
  exit 2
fi

SCRATCH="$(mktemp -d -t superpowers-sync-XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT

echo ">> Cloning $UPSTREAM_URL ($UPSTREAM_BRANCH) into scratch..."
git clone --depth 1 --branch "$UPSTREAM_BRANCH" "$UPSTREAM_URL" "$SCRATCH/upstream" >/dev/null 2>&1

UPSTREAM_REV="$(git -C "$SCRATCH/upstream" rev-parse --short HEAD)"
echo ">> Upstream at $UPSTREAM_REV"

SRC="$SCRATCH/upstream"
if [[ $SKILLS_ONLY -eq 1 ]]; then
  SRC="$SCRATCH/upstream/skills"
  if [[ ! -d "$SRC" ]]; then
    echo "upstream has no skills/ dir?" >&2; exit 2
  fi
fi

# Compute diff summary
echo
echo ">> Diff summary ($MODE mode) into $TARGET"
DIFF_OUT="$(diff -qr "$SRC" "$FULL_TARGET" 2>/dev/null || true)"
if [[ -z "$DIFF_OUT" ]]; then
  echo "   No differences. Vendored copy is up to date."
  exit 0
fi
echo "$DIFF_OUT" | sed 's/^/   /'

if [[ "$MODE" != "apply" ]]; then
  echo
  echo ">> Re-run with --apply to write changes."
  exit 0
fi

# Preserve local repo-management files
EXCLUDES=(
  --exclude='.git'
  --exclude='.gitattributes'
  --exclude='.gitignore'
  --exclude='node_modules'
  --exclude='CHANGELOG.md'
  --exclude='RELEASE-NOTES.md'
)

echo
echo ">> rsync --delete-after ..."
rsync -a --delete-after "${EXCLUDES[@]}" "$SRC"/ "$FULL_TARGET"/
echo ">> Done. Review with: git -C $REPO_ROOT diff -- $TARGET"
echo ">> Upstream rev: $UPSTREAM_REV"
