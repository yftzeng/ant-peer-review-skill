#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Tests precommit.sh and mutate-check.sh in a throwaway git repo built from the
# scripts beside this file, so it proves the kit AS SHIPPED. It stands in a tiny
# fast test (rc.test.sh) for the real suite, which keeps it to a few seconds even
# though mutate-check runs the gate three times per case.
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT" 2>/dev/null || :' EXIT
pass=0 fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n     %s\n' "$1" "$2"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$2] got [$3]"; fi; }

# A repo with the kit and one tracked test that depends on run_logged returning
# the command's status -- the property the mutation breaks.
mkrepo() {
  local r="$ROOT/$1"
  mkdir -p "$r/scripts" "$r/.ant"
  cp "$SRC/lib-job-output.sh" "$SRC/logged.sh" "$SRC/precommit.sh" "$SRC/mutate-check.sh" "$r/scripts/"
  printf 'logs_dir=logs\n' > "$r/.ant/config"
  cat > "$r/scripts/rc.test.sh" <<'T'
#!/usr/bin/env bash
cd "$(dirname "$0")/.." || exit 2
. scripts/lib-job-output.sh
run_logged logs/t/false.log "" false >/dev/null 2>&1 && { echo "run_logged returned 0 for false"; exit 1; }
run_logged logs/t/true.log "" true >/dev/null 2>&1 || { echo "run_logged returned non-zero for true"; exit 1; }
echo "rc ok"
T
  ( cd "$r" && git init -q . && git -c user.email=t@t -c user.name=t add scripts \
      && git -c user.email=t@t -c user.name=t commit -qm init ) >/dev/null 2>&1
  echo "$r"
}
last() { tail -n 1 "$1"; }
# `sed -i` is not portable: BSD sed (macOS) takes the next word as a backup
# suffix. Edit through a temp file instead.
sub() { sed "$1" "$2" > "$2.tmp" && mv "$2.tmp" "$2"; }

R=$(mkrepo green)
( cd "$R" && scripts/precommit.sh > "$ROOT/o1" 2>&1 ); rc=$?
check "precommit: green repo exits 0" 0 "$rc"
check "precommit: last line is the verdict" "precommit: ALL GATES PASS (1)" "$(last "$ROOT/o1")"
check "precommit: full output went to logs/precommit/" "rc ok" "$(cat "$R/logs/precommit/test-rc.log")"

# a failing tracked test: red, counted, and its log named
printf '#!/usr/bin/env bash\necho boom; exit 3\n' > "$R/scripts/boom.test.sh"
( cd "$R" && git add scripts/boom.test.sh && scripts/precommit.sh > "$ROOT/o2" 2>&1 ); rc=$?
check "precommit: a failing test makes it exit 1" 1 "$rc"
check "precommit: last line counts the failure" "precommit: 1 of 2 FAILED" "$(last "$ROOT/o2")"
check "precommit: the failure names its rc and log" 1 "$(grep -c 'boom (rc=3) -- logs/precommit/test-boom.log' "$ROOT/o2")"
check "precommit: the failure's tail is expanded" 1 "$(grep -c '^    boom$' "$ROOT/o2")"
( cd "$R" && git rm -q --cached scripts/boom.test.sh ) >/dev/null 2>&1

# untracked tests are invisible, and "ran nothing" is not green
E="$ROOT/empty"; mkdir -p "$E/scripts"; cp "$SRC/precommit.sh" "$E/scripts/"
printf '#!/usr/bin/env bash\nexit 0\n' > "$E/scripts/x.test.sh"
( cd "$E" && git init -q . && scripts/precommit.sh > "$ROOT/o3" 2>&1 ); rc=$?
check "precommit: nothing tracked -> exit 2, not green" 2 "$rc"
check "precommit: and it says why" 1 "$(grep -c 'is the \*.test.sh tracked' "$ROOT/o3")"

# the property the field report found: the gate must see run_logged break
cp "$R/scripts/lib-job-output.sh" "$ROOT/lib.orig"
sub 's/return "\$rc"/return 0/' "$R/scripts/lib-job-output.sh"
( cd "$R" && scripts/precommit.sh > "$ROOT/o4" 2>&1 ); rc=$?
check "precommit: red when run_logged is broken (it does not report through it)" 1 "$rc"
cp "$ROOT/lib.orig" "$R/scripts/lib-job-output.sh"

# the repo's own checks live in precommit.local.sh: sourced, counted, and able to raise the floor
printf 'one extra true\nMIN_TESTS=2\n' > "$R/scripts/precommit.local.sh"
( cd "$R" && scripts/precommit.sh > "$ROOT/o9" 2>&1 ); rc=$?
check "precommit: a local check is run and counted" "precommit: ALL GATES PASS (2)" "$(last "$ROOT/o9")"
printf 'one extra true\nMIN_TESTS=3\n' > "$R/scripts/precommit.local.sh"
( cd "$R" && scripts/precommit.sh > "$ROOT/o9b" 2>&1 ); rc=$?
check "precommit: a local floor above what ran -> exit 2" 2 "$rc"
printf 'one extra false\n' > "$R/scripts/precommit.local.sh"
( cd "$R" && scripts/precommit.sh > "$ROOT/o10" 2>&1 ); rc=$?
check "precommit: a failing local check makes it red" "precommit: 1 of 2 FAILED" "$(last "$ROOT/o10")"
rm -f "$R/scripts/precommit.local.sh"

# mutate-check against the shipped gate
( cd "$R" && scripts/mutate-check.sh > "$ROOT/o5" 2>&1 ); rc=$?
check "mutate-check: passes against precommit.sh" 0 "$rc"
check "mutate-check: last line is the verdict" "mutate-check: PASS" "$(last "$ROOT/o5")"
check "mutate-check: the library is restored byte-for-byte" 0 "$(cmp -s "$ROOT/lib.orig" "$R/scripts/lib-job-output.sh"; echo $?)"

# ...and against a gate that reports through logged.sh: it must catch the masking
cat > "$R/scripts/masking-gate.sh" <<'G'
#!/usr/bin/env bash
cd "$(dirname "$0")/.." || exit 2
scripts/logged.sh rc -- bash scripts/rc.test.sh
G
chmod +x "$R/scripts/masking-gate.sh"
( cd "$R" && scripts/mutate-check.sh scripts/masking-gate.sh > "$ROOT/o6" 2>&1 ); rc=$?
check "mutate-check: fails a gate that reports through logged.sh" 1 "$rc"
check "mutate-check: and says it stayed green" 1 "$(grep -c 'stayed GREEN with run_logged broken' "$ROOT/o6")"
check "mutate-check: restored after a failing check too" 0 "$(cmp -s "$ROOT/lib.orig" "$R/scripts/lib-job-output.sh"; echo $?)"

# a gate that is red before anything is mutated proves nothing
( cd "$R" && scripts/mutate-check.sh false > "$ROOT/o7" 2>&1 ); rc=$?
check "mutate-check: refuses a gate that is already red" 1 "$rc"
check "mutate-check: and leaves the library untouched" 0 "$(cmp -s "$ROOT/lib.orig" "$R/scripts/lib-job-output.sh"; echo $?)"

# the anchor must exist exactly once -- matched literally, not as a regex
sub 's/return "\$rc"/return "$rc2"/' "$R/scripts/lib-job-output.sh"
( cd "$R" && scripts/mutate-check.sh > "$ROOT/o8" 2>&1 ); rc=$?
check "mutate-check: missing anchor -> exit 2" 2 "$rc"
check "mutate-check: and it names the count" 1 "$(grep -c "occurs 0 times" "$ROOT/o8")"
cp "$ROOT/lib.orig" "$R/scripts/lib-job-output.sh"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
