#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# A minimal gate for a repo that has none: every TRACKED `*.test.sh`, run
# directly, one verdict line at the end.
#
#   scripts/precommit.sh          -> last line: `precommit: ALL GATES PASS (N)`
#                                    or `precommit: K of N FAILED`
#
# Installed only when the target repo has no gate of its own (`ant init` skips it otherwise).
# Keep THIS file identical to the template: the repo's own checks and floor go in
# scripts/precommit.local.sh, which is sourced below and may call `one <name> <cmd…>`
# and set MIN_TESTS. Field report, 2026-09-25: adding a line here instead made
# precommit.test.sh (which runs THIS file in a throwaway repo) go red -- the
# throwaway repo has none of the repo's other checks. Separate files also make an
# upgrade a plain copy.
#
# Three decisions here are load-bearing:
#
# 1. The tests are run DIRECTLY, not through `scripts/logged.sh`. logged.sh is
#    built on `run_logged`, and lib-job-output.test.sh is the test OF
#    run_logged -- a gate that reports through the thing under test cannot see
#    it break. Field report, 2026-09-25: mutating `return "$rc"` to `return 0`
#    turned the suite red (37 passed, 1 failed) while a logged.sh-based gate
#    printed ALL GATES PASS. The reporting layer must not be the tested layer.
# 2. Discovery is `git ls-files`, so a new test needs no edit here -- and an
#    UNTRACKED test is invisible. That is why the floor exists: before the first
#    `git add`, discovery finds nothing, and "ran nothing" must not read as green.
# 3. Full output goes to <logs_dir>/precommit/<name>.log (bounded: one file per test,
#    overwritten each run); only a failure expands its tail.
set -uo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO" || { echo "precommit: FAIL (cannot cd to $REPO)"; exit 2; }
MIN_TESTS=${PRECOMMIT_MIN_TESTS:-1}
TAIL=${JOB_TAIL_LINES:-15}
# The kit's one sink root: logs_dir= in .ant/config, default .ant/work/logs
# (it ignores itself). Read here rather than from lib-job-output.sh, which
# this script must not depend on.
LOGS="$(sed -n 's/^logs_dir=//p' .ant/config 2>/dev/null | head -1)"; LOGS="${LOGS:-.ant/work/logs}"
L="$LOGS/precommit"
mkdir -p "$L" || { echo "precommit: FAIL (cannot create $L)"; exit 2; }

n=0 fail=0
one() {
  local name=$1 rc; shift
  n=$((n + 1))
  "$@" > "$L/$name.log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "  ✓ $name"
  else
    fail=$((fail + 1))
    echo "  ✗ $name (rc=$rc) -- $L/$name.log"
    tail -n "$TAIL" "$L/$name.log" | sed 's/^/    /'
  fi
}

while IFS= read -r t; do
  one "test-$(basename "$t" .test.sh)" bash "$t"
done < <(git ls-files '*.test.sh')

# The repo's own checks (and a higher MIN_TESTS), if it has any.
# shellcheck source=/dev/null
[ -f scripts/precommit.local.sh ] && . scripts/precommit.local.sh

if [ "$n" -lt "$MIN_TESTS" ]; then
  echo "precommit: FAIL (found $n checks, need >= $MIN_TESTS -- is the *.test.sh tracked? git ls-files only sees tracked files)"
  exit 2
fi
if [ "$fail" -eq 0 ]; then
  echo "precommit: ALL GATES PASS ($n)"
else
  echo "precommit: $fail of $n FAILED"
  exit 1
fi
