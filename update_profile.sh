#!/bin/bash
# Update profile stats and regenerate SVGs
# Run via launchd daily or manually

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "$(date): Starting profile update..."

# Regenerate SVGs with fresh stats
/usr/bin/python3 generate_svg.py

# Check if there are changes
if git diff --quiet dark_mode.svg light_mode.svg; then
    echo "$(date): No changes to commit"
else
    echo "$(date): Changes detected, committing..."
    git add dark_mode.svg light_mode.svg cache/
    git commit -m "Update stats $(date '+%Y-%m-%d')"
    # Conflict-proof sync: merge origin keeping our freshly-generated files.
    # Avoids the rebase-strand that froze pushes (and the token count) for ~2 months.
    git fetch origin
    git merge -X ours --no-edit origin/main
    git push origin main
    echo "$(date): Pushed to GitHub"
fi

echo "$(date): Profile update complete"
