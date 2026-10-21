#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Install the pre-commit hook that admits only commits scripts/commit.sh
# cleared, and prove git will run it.
#
#   scripts/install-hook.sh            -> last line `install-hook: OK (...)`
#
# Why a script and not `cp`, measured:
#   - without `chmod +x`, git SKIPS the hook with a one-line hint and the commit
#     exits 0 -- a gate that never runs, reading as installed;
#   - in a worktree `.git` is a file, so a path under it does not exist;
#   - under `core.hooksPath` git never looks in .git/hooks at all.
# `git rev-parse --git-path hooks` answers all three: it names the directory git
# will actually read.
#
# Hooks are not versioned: every clone runs this once. A hook this script did
# not write is refused, not overwritten -- merging two hooks is the owner's call.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC="$HERE/pre-commit.hook"
MARK="# ant-mode:install-hook"

[ -f "$SRC" ] || { echo "install-hook: FAIL ($SRC not found)"; exit 2; }
dir=$(git rev-parse --git-path hooks 2>/dev/null) \
  || { echo "install-hook: FAIL (not inside a git repository)"; exit 2; }
hook="$dir/pre-commit"

if [ -e "$hook" ] && ! grep -qF -- "$MARK" "$hook"; then
  echo "install-hook: FAIL ($hook exists and was not written by this script -- merge it by hand)"
  exit 2
fi

mkdir -p "$dir" || { echo "install-hook: FAIL (cannot create $dir)"; exit 2; }
cp "$SRC" "$hook" || { echo "install-hook: FAIL (cannot write $hook)"; exit 2; }
chmod +x "$hook" || { echo "install-hook: FAIL (cannot make $hook executable)"; exit 2; }
# The claim is "git will run it", and the executable bit is the half of that
# git checks silently. Read it back rather than trust chmod's status.
[ -x "$hook" ] || { echo "install-hook: FAIL ($hook is still not executable)"; exit 2; }

echo "install-hook: OK ($hook admits only commits scripts/commit.sh cleared; hooks are not versioned -- every clone runs this once)"
