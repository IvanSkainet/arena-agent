#!/bin/sh
# Tracked executable helper, not a temporary state file; contains no secret.
case "$1" in
    *Username*) printf '%s\n' 'x-access-token' ;;
    *) printf '%s\n' "$GH_TOKEN" ;;
esac
