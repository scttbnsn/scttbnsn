#!/bin/bash
# Update profile stats and regenerate SVGs. Run via launchd daily (04:00) or manually.
# Robust against the two-writer race with the GitHub Action and the cron job:
# self-heals any stranded git state and retries pushes (see scripts/lib-git-sync.sh),
# so it can never get permanently stuck the way the Apr-2026 rebase strand did.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# shellcheck source=scripts/lib-git-sync.sh
. "$SCRIPT_DIR/scripts/lib-git-sync.sh"

echo "$(date): Starting profile update..."

# Clear any leftover rebase/merge state from a previously interrupted run, then
# make sure we're on main (a cleared strand can leave HEAD detached).
git_selfheal
git checkout main

# Regenerate SVGs with fresh stats
/usr/bin/python3 generate_svg.py

# Commit + push only if the rendered output actually changed
if git diff --quiet dark_mode.svg light_mode.svg; then
    echo "$(date): No changes to commit"
else
    echo "$(date): Changes detected, committing..."
    git add dark_mode.svg light_mode.svg cache/
    git commit -m "Update stats $(date '+%Y-%m-%d')"
    git_sync_push ours main
    echo "$(date): Pushed to GitHub"
fi

echo "$(date): Profile update complete"
