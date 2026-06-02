#!/usr/bin/env bash
# Shared robust-sync helpers for the three profile-stats writers:
#   - update_profile.sh               (launchd, 04:00 local) -> strategy "ours"
#   - scripts/update-claude-stats.sh  (cron,    23:30 local) -> strategy "ours"
#   - .github/workflows/update-stats.yml (Action, ~nightly)  -> strategy "theirs"
#
# Goal: NO writer can ever leave the repo permanently stuck. The Apr-2026 outage
# was a `git pull --rebase` that conflicted on the generated SVGs, stranded a
# .git/rebase-merge directory, and then every subsequent nightly run aborted at
# that strand for ~2 months. These helpers (a) auto-clear any leftover
# in-progress state at the start of a run and (b) integrate origin + push with a
# conflict-proof merge plus a push-race retry loop.
#
# Why different strategies: local writers compute the real Claude token count
# from ~/.claude logs, so on conflict they keep their own files (-X ours). The
# Action runs on GitHub and cannot see those logs, so it must defer to whatever
# was last pushed (-X theirs) and never regress the count with stale data.

# Clear leftover rebase/merge/cherry-pick state from a previously interrupted
# run so a strand can never persist across runs. Safe to call when clean.
git_selfheal() {
  local gd
  gd="$(git rev-parse --git-dir 2>/dev/null)" || return 0
  if [ -d "$gd/rebase-merge" ] || [ -d "$gd/rebase-apply" ]; then
    echo "git_selfheal: clearing stranded rebase state" >&2
    git rebase --quit 2>/dev/null || git rebase --abort 2>/dev/null \
      || rm -rf "$gd/rebase-merge" "$gd/rebase-apply"
  fi
  if [ -f "$gd/MERGE_HEAD" ]; then
    echo "git_selfheal: clearing stranded merge state" >&2
    git merge --abort 2>/dev/null || true
  fi
  if [ -f "$gd/CHERRY_PICK_HEAD" ]; then
    echo "git_selfheal: clearing stranded cherry-pick state" >&2
    git cherry-pick --abort 2>/dev/null || true
  fi
  # A conflicted stop can leave unmerged entries in the index even after the
  # rebase/merge dir is gone; reset index+worktree to the current commit (this
  # does NOT move any branch ref, so no commits are lost) so the next merge runs.
  if [ -n "$(git ls-files --unmerged 2>/dev/null)" ]; then
    echo "git_selfheal: resetting leftover unmerged index to HEAD" >&2
    git reset --hard HEAD 2>/dev/null || true
  fi
  return 0
}

# git_sync_push <ours|theirs> [branch]
# Integrate origin/<branch> and push HEAD there, retrying through push races
# with the other writers. Content conflicts on the generated files are
# auto-resolved toward the chosen side. A structural conflict the strategy can't
# resolve (e.g. modify/delete) is aborted cleanly instead of left to strand --
# the next run self-heals and retries. Merges FETCH_HEAD (not origin/<branch>)
# so it works even where no remote-tracking ref exists (e.g. Actions checkout).
git_sync_push() {
  local strategy="${1:?usage: git_sync_push <ours|theirs> [branch]}"
  local branch="${2:-main}"
  local attempt
  for attempt in 1 2 3 4 5; do
    if ! git fetch origin "$branch"; then
      echo "git_sync_push: fetch failed (attempt $attempt), retrying" >&2
      sleep "$((attempt * 2))"
      continue
    fi
    if git merge "-X${strategy}" --no-edit FETCH_HEAD; then
      : # merged (clean, fast-forward, or content conflict auto-resolved)
    else
      echo "git_sync_push: merge could not auto-resolve; aborting cleanly (retry next run)" >&2
      git merge --abort 2>/dev/null || true
      return 1
    fi
    if git push origin "HEAD:${branch}"; then
      echo "git_sync_push: pushed on attempt $attempt" >&2
      return 0
    fi
    echo "git_sync_push: push rejected (raced another writer), re-syncing (attempt $attempt)" >&2
    sleep "$((attempt * 2))"
  done
  echo "git_sync_push: could not push after retries; will self-heal and retry next run" >&2
  return 1
}
