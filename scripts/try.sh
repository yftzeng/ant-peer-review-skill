#!/usr/bin/env bash
# Run ant-peer-review from this checkout with every byte of user data kept in
# ./workspaces (git-ignored; Claude is denied reading it in .claude/settings.json).
#   scripts/try.sh new --backend fake      scripts/try.sh runs
set -euo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export ANT_PEER_REVIEW_HOME="$REPO/workspaces"
mkdir -p "$ANT_PEER_REVIEW_HOME"
# uv run uses an editable install in ./.venv (git-ignored), so it always runs the
# current working tree; uvx caches builds by version and can serve stale code.
exec uv run --quiet --project "$REPO" --python 3.12 ant-peer-review "$@"
