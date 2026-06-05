#!/usr/bin/env bash
# Agrim SDLC — worktree setup
# Usage: setup.sh <branch-name> <plan-slug>
#
# Creates an isolated git worktree for the plan branch, runs the project's
# test command to verify a clean baseline, and prints the worktree path.
#
# On success: prints WORKTREE_PATH=<path> and exits 0
# On failure: prints an error message and exits 1
#
# Requires: git 2.5+, project-rules.md with a [test command] section

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: setup.sh <branch-name> <plan-slug>" >&2
    exit 1
fi

BRANCH="$1"
SLUG="$2"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROJECT_RULES="${REPO_ROOT}/.claude/project-rules.md"

# ── 1. Read test command from project-rules.md ──────────────────────────────

extract_test_command() {
    awk '
        /^## test command/ { in_block=1; next }
        in_block && /^```/ {
            if (found_open) { exit }
            found_open=1; next
        }
        in_block && found_open && !/^</ { print; exit }
        /^## / && in_block && NR > 1 { exit }
    ' "$1" | sed 's/^[[:space:]]*//' | grep -v '^#' | head -1
}

TEST_CMD=$(extract_test_command "${PROJECT_RULES}" 2>/dev/null || true)

if [ -z "$TEST_CMD" ] || echo "$TEST_CMD" | grep -q '<command>'; then
    echo "ERROR: No test command found in .claude/project-rules.md." >&2
    echo "       Fill in the '## test command' section before running setup." >&2
    exit 1
fi

# ── 2. Check for uncommitted changes on the base branch ─────────────────────

cd "${REPO_ROOT}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "ERROR: Not inside a git repository." >&2
    exit 1
fi

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "ERROR: Uncommitted changes in the working tree." >&2
    echo "       Commit or stash before creating a worktree." >&2
    exit 1
fi

# ── 3. Create the worktree ───────────────────────────────────────────────────

WORKTREE_DIR="${TMPDIR:-/tmp}/agrim-work/${SLUG}"

# Clean up any stale worktree at this path
if [ -d "${WORKTREE_DIR}" ]; then
    echo "Cleaning up stale worktree at ${WORKTREE_DIR}..." >&2
    git worktree remove --force "${WORKTREE_DIR}" 2>/dev/null || rm -rf "${WORKTREE_DIR}"
fi

# Remove stale branch if it exists
if git show-ref --verify --quiet "refs/heads/${BRANCH}" 2>/dev/null; then
    echo "Branch '${BRANCH}' already exists — using it as-is." >&2
    git worktree add "${WORKTREE_DIR}" "${BRANCH}"
else
    git worktree add -b "${BRANCH}" "${WORKTREE_DIR}" HEAD
fi

echo "Created worktree at: ${WORKTREE_DIR}" >&2

# ── 4. Run baseline test in the worktree ────────────────────────────────────

echo "Running baseline tests: ${TEST_CMD}" >&2

cd "${WORKTREE_DIR}"

if eval "${TEST_CMD}" >/dev/null 2>&1; then
    echo "Baseline tests: PASS" >&2
else
    echo "ERROR: Baseline tests failed in the worktree before any changes." >&2
    echo "       Fix failing tests on the base branch first." >&2
    echo "       Cleaning up worktree..." >&2
    cd "${REPO_ROOT}"
    git worktree remove --force "${WORKTREE_DIR}" 2>/dev/null || true
    git branch -D "${BRANCH}" 2>/dev/null || true
    exit 1
fi

# ── 5. Output the worktree path for the caller ──────────────────────────────

echo "WORKTREE_PATH=${WORKTREE_DIR}"
exit 0
