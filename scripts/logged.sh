#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Run something noisy and read the answer instead of the output.
#
#   scripts/logged.sh <name> [--progress <ere>] -- <command> [args...]
#
# Exists as a script, not as a note, because the pattern is easy -- which is
# exactly why it gets hand-rolled, and the hand-rolled version is where
# `| tail` ends up between a command and the status read back from it.
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./lib-job-output.sh
. "$REPO/scripts/lib-job-output.sh"

LOGGED_DIR="${LOGGED_DIR:-$(ant_logs_dir "$REPO")/logged}"
# Found by content, not by line number: `sed -n '3,4p'` printed the
# description and a blank line, and never the usage line itself -- on the one
# path whose entire job is to print it.
usage() { sed -n '/^#   scripts\//p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

name="${1:-}"
# One ERE, in the library: the sweep's correctness depends on it (see there).
[[ "$name" =~ $JOB_NAME_ERE ]] || {
  echo "logged: '${name}' is not a plain name (letters, digits, _ and - only)" >&2; exit 2; }
shift

ere=""
if [ "${1:-}" = "--progress" ]; then
  [ $# -ge 2 ] || usage
  ere="$2"; shift 2
fi
[ "${1:-}" = "--" ] || usage
shift
[ $# -ge 1 ] || usage

mkdir -p "$LOGGED_DIR"
# Keyed on `log`: a log with no running job behind it IS the finished artefact.
sweep_stale_logs "$LOGGED_DIR" log

rc=0
started=$SECONDS
run_logged "$LOGGED_DIR/$name.log" "$ere" "$@" || rc=$?

# Say the outcome out loud. A bare command line and no verdict reads exactly
# like a run that never happened, and the reader should not have to go and
# fetch $? to tell the difference.
if [ "$rc" -eq 0 ]; then
  echo "  ✓ $name ($((SECONDS - started))s) -- ${LOGGED_DIR#"$PWD"/}/$name.log"
else
  echo "  ✗ $name exited $rc after $((SECONDS - started))s"
fi
exit "$rc"
