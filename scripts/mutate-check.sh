#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# The kit's own negative control, as a script: break run_logged on purpose, and require the
# repo's GATE -- not just the suite -- to go red; then restore and require green.
#
#   scripts/mutate-check.sh [gate command ...]     default: scripts/precommit.sh
#
# Why a script and not an instruction. Field report, 2026-09-25, doing it by hand:
#   - `grep -c 'return "$rc"'` answered 0 for a line that exists (in a regex the
#     `$` is an anchor), the `&&` chain stopped there, and the "mutated gate"
#     rc that got printed was grep's. The mutation never happened, and the
#     output read like a finished check.
#   - once it did happen, the suite went red but the gate stayed green, because
#     that gate ran the suite through logged.sh. Asking only "does the suite go
#     red?" cannot see that; this asks the gate.
# So: the anchor is matched with -F and must occur exactly once, the file is
# restored by a trap whatever happens, and restoration is proven with cmp.
set -uo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO" || { echo "mutate-check: FAIL (cannot cd to $REPO)"; exit 2; }
LIB=scripts/lib-job-output.sh
ANCHOR='return "$rc"'
if [ "$#" -gt 0 ]; then GATE=("$@"); else GATE=(scripts/precommit.sh); fi
# The kit's one sink root: logs_dir= in .ant/config, default .ant/work/logs
# (it ignores itself). Read here rather than from lib-job-output.sh, which
# this script must not depend on.
LOGS="$(sed -n 's/^logs_dir=//p' .ant/config 2>/dev/null | head -1)"; LOGS="${LOGS:-.ant/work/logs}"
LOG="$LOGS/mutate-check"
mkdir -p "$LOG" || { echo "mutate-check: FAIL (cannot create $LOG)"; exit 2; }

[ -f "$LIB" ] || { echo "mutate-check: FAIL ($LIB not found)"; exit 2; }
hits=$(grep -cF -- "$ANCHOR" "$LIB")
[ "$hits" = 1 ] || { echo "mutate-check: FAIL (anchor '$ANCHOR' occurs $hits times in $LIB, need exactly 1)"; exit 2; }
line=$(grep -nF -- "$ANCHOR" "$LIB" | cut -d: -f1)

gate() { "${GATE[@]}" > "$LOG/$1.log" 2>&1; }

echo "== baseline: the gate must be green before the mutation means anything"
gate baseline; rc=$?
[ "$rc" -eq 0 ] || { echo "mutate-check: FAIL (gate is already red, rc=$rc -- see $LOG/baseline.log)"; exit 1; }

BAK=$(mktemp) || { echo "mutate-check: FAIL (mktemp)"; exit 2; }
cp -p "$LIB" "$BAK"
# The proof of restoration is a byte comparison against the backup, taken BEFORE
# the backup is deleted -- "cp exited 0" is not the same claim.
restored_ok=0
restore() { cp -p "$BAK" "$LIB" && cmp -s "$BAK" "$LIB" && restored_ok=1; rm -f "$BAK"; }
trap restore EXIT

echo "== mutate $LIB:$line  ($ANCHOR -> return 0)"
awk -v n="$line" 'NR == n { sub(/return "\$rc"/, "return 0") } { print }' "$BAK" > "$LIB"
if cmp -s "$BAK" "$LIB"; then echo "mutate-check: FAIL (the mutation changed nothing)"; exit 2; fi

gate mutated; mrc=$?
restore; trap - EXIT
[ "$restored_ok" = 1 ] || { echo "mutate-check: FAIL ($LIB could not be restored byte-for-byte -- fix it by hand)"; exit 2; }
echo "== restored (byte-identical to before)"

gate restored; grc=$?

if [ "$mrc" -eq 0 ]; then
  echo "  ✗ the gate stayed GREEN with run_logged broken -- it cannot see its own kit fail (does it run the suite through logged.sh?) -- $LOG/mutated.log"
  echo "mutate-check: FAIL"
  exit 1
fi
echo "  ✓ the gate went red (rc=$mrc) with run_logged broken"
if [ "$grc" -ne 0 ]; then
  echo "  ✗ the gate is still red after restoring (rc=$grc) -- $LOG/restored.log"
  echo "mutate-check: FAIL"
  exit 1
fi
echo "  ✓ the gate is green again after restoring"
echo "mutate-check: PASS"
