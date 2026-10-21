#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# mutants.sh: every mutant is applied, run, and undone, and the score counts
# only mutants it can prove it ran.
#
# Runs in a throwaway repo against the script beside this file, so it proves
# the kit AS SHIPPED.
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T" 2>/dev/null || :' EXIT
pass=0 fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
# Each case is a string evaluated at check time.
# shellcheck disable=SC2016
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
last() { tail -n 1 "$1"; }

R="$T/repo"
mkdir -p "$R/scripts" "$R/src"
cp "$SRC/mutants.sh" "$R/scripts/"; chmod +x "$R/scripts/mutants.sh"
cd "$R" || exit 2
git init -q . >/dev/null 2>&1
# The subject: a clamp, and a test that checks both edges.
cat > src/clamp.sh <<'S'
clamp() { if [ "$1" -lt 0 ]; then echo 0; elif [ "$1" -gt 9 ]; then echo 9; else echo "$1"; fi; }
S
cat > test.sh <<'S'
. src/clamp.sh
[ "$(clamp -1)" = 0 ] && [ "$(clamp 10)" = 9 ] && [ "$(clamp 5)" = 5 ]
S
cp src/clamp.sh "$T/orig"
# Read inside the eval strings below.
# shellcheck disable=SC2034
M=scripts/mutants.sh

cat > "$T/killed.list" <<'L'
# both edges are tested, so both mutants die. (-lt 0 -> -le 0 would live:
# clamp 0 is 0 either way -- an equivalent mutant at every tested point.)
@@ src/clamp.sh
- -lt 0
+ -gt 0
- echo 9
+ echo 8
L
# @S-mutants-001
check "every mutant killed: N/N, exit 0" '"$M" -f "$T/killed.list" -- bash test.sh > "$T/o1" 2>&1 && last "$T/o1" | grep -q "^mutants: 2/2 killed"'
check "every mutant is named with its outcome" '[ "$(grep -c "killed" "$T/o1")" -ge 3 ]'
# @N-mutants-001
check "the file is byte-identical afterwards" 'cmp -s src/clamp.sh "$T/orig"'

cat > "$T/survivor.list" <<'L'
@@ src/clamp.sh
- echo 9
+ echo 8
# 0 maps to 0 either way, so this one lives: the test has no case at 0
- -lt 0
+ -lt 1
L
# @S-mutants-002
check "a survivor fails it: exit 1, named, score on the last line" \
  '! "$M" -f "$T/survivor.list" -- bash test.sh > "$T/o2" 2>&1 && grep -q "SURVIVED.*-lt 1" "$T/o2" && last "$T/o2" | grep -q "^mutants: FAILED (1/2 killed"'
check "a survivor run still restores the file" 'cmp -s src/clamp.sh "$T/orig"'

printf '@@ src/clamp.sh\n- not in the file\n+ x\n' > "$T/absent.list"
# @S-mutants-003
check "an anchor that is absent is refused (exit 2)" '"$M" -f "$T/absent.list" -- bash test.sh > "$T/o3" 2>&1; [ $? -eq 2 ] && grep -q "occurs 0 times" "$T/o3"'
printf '@@ src/clamp.sh\n- echo\n+ printf\n' > "$T/twice.list"
check "an anchor that occurs twice is refused (exit 2)" '"$M" -f "$T/twice.list" -- bash test.sh > "$T/o4" 2>&1; [ $? -eq 2 ] && grep -qE "occurs [2-9] times" "$T/o4"'
check "a refused list leaves the file untouched" 'cmp -s src/clamp.sh "$T/orig"'
printf '@@ src/clamp.sh\n- echo 9\n+ echo 9\n' > "$T/same.list"
check "a mutant that changes nothing is refused (exit 2)" '"$M" -f "$T/same.list" -- bash test.sh > "$T/o9" 2>&1; [ $? -eq 2 ] && grep -q "changes nothing" "$T/o9"'
printf '@@ src/clamp.sh\n- echo 9\n' > "$T/half.list"
check "a - line without its + line is refused (exit 2)" '"$M" -f "$T/half.list" -- bash test.sh >/dev/null 2>&1; [ $? -eq 2 ]'
check "a suite that is red before mutating is refused (exit 2)" \
  '"$M" -f "$T/killed.list" -- false > "$T/o5" 2>&1; [ $? -eq 2 ] && grep -q "red before any mutant" "$T/o5"'
check "a test command that cannot run (127) is not a kill (exit 2)" \
  '"$M" -f "$T/killed.list" -- no-such-test-runner > "$T/o6" 2>&1; [ $? -eq 2 ] && cmp -s src/clamp.sh "$T/orig"'
# Green on the first run, red on every later one: the mutant "dies", and the
# suite is red after restoring -- a state no score should come out of.
cat > "$T/flaky.sh" <<'S'
n=$(cat "$1" 2>/dev/null || echo 0); echo $((n + 1)) > "$1"; [ "$n" -eq 0 ]
S
# @S-mutants-005
check "a suite red after restoring is refused (exit 2)" \
  '"$M" -f "$T/killed.list" -- bash "$T/flaky.sh" "$T/count" > "$T/o8" 2>&1; [ $? -eq 2 ] && grep -q "red after restoring" "$T/o8"'
check "no list is refused (exit 2)" '"$M" -f "$T/nope.list" -- bash test.sh >/dev/null 2>&1; [ $? -eq 2 ]'

# Interrupted mid-run (the first mutant's test sleeps): the original is back
# and the run says it was interrupted. Without the INT/TERM trap bash's EXIT
# trap still restores the file, so the message is what proves on_signal ran.
# @S-mutants-004
check "an interrupt restores the file" \
  '( "$M" -f "$T/killed.list" -- bash -c "grep -q -- \"-gt 0\" src/clamp.sh && sleep 30; exit 0" > "$T/o7" 2>&1 & echo $! > "$T/pid"; wait ) & sleep 3; kill -TERM "$(cat "$T/pid")" 2>/dev/null; wait; cmp -s src/clamp.sh "$T/orig" && grep -q "interrupted; every file restored" "$T/o7"'

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
