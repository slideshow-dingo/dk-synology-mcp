#!/usr/bin/env bash
#
# sync-upstream.sh
# Sync this private fork with the public upstream repository.
#
# Usage: ./scripts/sync-upstream.sh [--rebase]
#
# This script:
# 1. Fetches the latest commits from the upstream (origin) repository
# 2. Merges (or rebases) upstream/main into your local main branch
# 3. Pushes the updated main to your private fork
#
# Requirements:
# - Run from the repository root directory
# - Git remotes must be configured:
#   - 'origin' points to upstream (https://github.com/DRVBSS/dk-synology-mcp.git)
#   - 'fork' points to your private repo (https://github.com/karabayogo/dk-synology-mcp.git)
#

set -euo pipefail

REBASE_FLAG="${1:-}"

echo "🔄 Syncing with upstream repository..."

# Ensure we're on main branch
git checkout main

# Fetch upstream changes
echo "📥 Fetching upstream (origin)..."
git fetch origin

# Merge or rebase
if [[ "$REBASE_FLAG" == "--rebase" ]]; then
    echo "🔀 Rebasing onto upstream/main..."
    git rebase origin/main
else
    echo "🔗 Merging upstream/main..."
    git merge origin/main --no-edit
fi

# Push to private fork
echo "📤 Pushing to private fork..."
git push fork main

echo "✅ Sync complete!"
