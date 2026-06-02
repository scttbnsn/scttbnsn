#!/usr/bin/env bash
# Updates the Claude Code stats cache and pushes. Runs via cron (23:30 local).
# Robust against the two-writer race (see scripts/lib-git-sync.sh): self-heals
# any stranded git state and retries pushes, so it can never stay stuck. If its
# push ever fails, the launchd writer picks up the local commit and pushes it.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib-git-sync.sh
. "$REPO_DIR/scripts/lib-git-sync.sh"

# Clear any stranded state first (so checkout can't be blocked), then get onto
# main and fast-forward to origin.
git_selfheal
git checkout main --quiet
git fetch origin main --quiet
git merge -X ours --no-edit FETCH_HEAD --quiet || git merge --abort 2>/dev/null || true

# Refresh the stats cache from local Claude logs + GitHub API
/opt/homebrew/bin/python3 preview.py --save

# Commit + push only if the cache changed
if ! git diff --quiet cache/; then
  git add cache/
  git commit -m "Update profile stats" --quiet
  git_sync_push ours main
fi
