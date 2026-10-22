#!/usr/bin/env bash
# Run ant-peer-review from this checkout with every byte of user data kept in
# ./workspaces (git-ignored; Claude is denied reading it in .claude/settings.json).
#   scripts/try.sh new --backend fake      scripts/try.sh runs
# Rebuilds from the working tree on each call, so code edits take effect at once.
set -euo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export ANT_PEER_REVIEW_HOME="$REPO/workspaces"
mkdir -p "$ANT_PEER_REVIEW_HOME"
exec uvx --quiet --python 3.12 --refresh-package ant-peer-review --from "$REPO" ant-peer-review "$@"
