#!/usr/bin/env bash
# Updates Claude Code stats cache and pushes to remote.
# Runs via cron before the CI workflow (midnight UTC) so stats are fresh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Ensure we're on main and up to date (conflict-proof merge — never strands a rebase)
git checkout main --quiet
git fetch origin --quiet
git merge -X ours --no-edit origin/main --quiet

# Update the stats cache with latest local Claude data
/opt/homebrew/bin/python3 preview.py --save

# Commit and push only if cache changed
if ! git diff --quiet cache/; then
  git add cache/
  git commit -m "Update profile stats" --quiet
  git fetch origin --quiet
  git merge -X ours --no-edit origin/main --quiet
  git push origin main --quiet
fi
