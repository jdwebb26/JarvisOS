#!/usr/bin/env bash
# worktree.sh — manage implementation worktrees for safe feature branch work
#
# The live runtime (gateway, HAL, timers) commits to whatever branch is
# checked out in the primary worktree (~/.openclaw/workspace/jarvis-v5).
# To prevent branch pollution during feature work, use a separate git
# worktree. The primary worktree stays on main; the worktree has its
# own checked-out branch.
#
# Usage:
#   bash scripts/worktree.sh create <branch-name>   # create worktree + branch
#   bash scripts/worktree.sh list                    # list active worktrees
#   bash scripts/worktree.sh remove <branch-name>    # remove a worktree
#   bash scripts/worktree.sh cd <branch-name>        # print the worktree path (for cd)
#   bash scripts/worktree.sh merge <branch-name>     # merge worktree branch into main
#
# Worktrees live in: ~/.openclaw/workspace/jarvis-v5-work/<branch-name>/
#
# IMPORTANT: Never check out a feature branch in the primary worktree.
# Always use this script or git worktree directly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_ROOT="$HOME/.openclaw/workspace/jarvis-v5-work"

mkdir -p "$WORK_ROOT"

usage() {
  echo "Usage: bash scripts/worktree.sh <command> [branch-name]"
  echo ""
  echo "Commands:"
  echo "  create <branch>   Create worktree for a new or existing branch"
  echo "  list              List active worktrees"
  echo "  remove <branch>   Remove a worktree (branch is kept)"
  echo "  cd <branch>       Print worktree path (use with: cd \$(bash scripts/worktree.sh cd <branch>))"
  echo "  merge <branch>    Merge worktree branch into main (in primary worktree)"
  echo ""
  echo "Worktree location: $WORK_ROOT/<branch-name>/"
}

cmd_create() {
  local branch="${1:?branch name required}"
  local worktree_path="$WORK_ROOT/$branch"

  if [ -d "$worktree_path" ]; then
    echo "Worktree already exists: $worktree_path"
    echo "To use it: cd $worktree_path"
    return 0
  fi

  # Check if branch exists
  if git -C "$REPO_ROOT" rev-parse --verify "$branch" >/dev/null 2>&1; then
    echo "Branch '$branch' exists, creating worktree..."
    git -C "$REPO_ROOT" worktree add "$worktree_path" "$branch"
  else
    echo "Creating new branch '$branch' from main..."
    git -C "$REPO_ROOT" worktree add -b "$branch" "$worktree_path" main
  fi

  echo ""
  echo "Worktree ready: $worktree_path"
  echo "Primary worktree remains on: $(git -C "$REPO_ROOT" branch --show-current)"
  echo ""
  echo "To start working:"
  echo "  cd $worktree_path"
}

cmd_list() {
  echo "Active worktrees:"
  git -C "$REPO_ROOT" worktree list
  echo ""

  # Show which are in the work directory
  local count=0
  for d in "$WORK_ROOT"/*/; do
    [ -d "$d" ] || continue
    local name="$(basename "$d")"
    local branch="$(git -C "$d" branch --show-current 2>/dev/null || echo '?')"
    echo "  work/$name → branch: $branch"
    count=$((count + 1))
  done
  if [ "$count" -eq 0 ]; then
    echo "  (no implementation worktrees)"
  fi
}

cmd_remove() {
  local branch="${1:?branch name required}"
  local worktree_path="$WORK_ROOT/$branch"

  if [ ! -d "$worktree_path" ]; then
    echo "No worktree at: $worktree_path"
    return 1
  fi

  git -C "$REPO_ROOT" worktree remove "$worktree_path"
  echo "Removed worktree: $worktree_path"
  echo "Branch '$branch' is still available (not deleted)."
}

cmd_cd() {
  local branch="${1:?branch name required}"
  local worktree_path="$WORK_ROOT/$branch"

  if [ ! -d "$worktree_path" ]; then
    echo "No worktree at: $worktree_path" >&2
    echo "Create one first: bash scripts/worktree.sh create $branch" >&2
    return 1
  fi

  echo "$worktree_path"
}

cmd_merge() {
  local branch="${1:?branch name required}"

  # Verify we're in the primary worktree on main
  local current
  current="$(git -C "$REPO_ROOT" branch --show-current)"
  if [ "$current" != "main" ]; then
    echo "ERROR: Primary worktree is on '$current', not 'main'."
    echo "Switch to main first: git -C $REPO_ROOT checkout main"
    return 1
  fi

  # Verify branch exists
  if ! git -C "$REPO_ROOT" rev-parse --verify "$branch" >/dev/null 2>&1; then
    echo "ERROR: Branch '$branch' not found."
    return 1
  fi

  echo "Merging '$branch' into main in primary worktree..."
  git -C "$REPO_ROOT" merge "$branch" --no-ff -m "merge: $branch into main"
  echo "Done. Consider removing the worktree:"
  echo "  bash scripts/worktree.sh remove $branch"
}

# ── Dispatch ──

case "${1:-}" in
  create) cmd_create "${2:-}" ;;
  list)   cmd_list ;;
  remove) cmd_remove "${2:-}" ;;
  cd)     cmd_cd "${2:-}" ;;
  merge)  cmd_merge "${2:-}" ;;
  *)      usage ;;
esac
