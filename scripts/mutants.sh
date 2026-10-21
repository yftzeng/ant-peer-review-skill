#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Manual mutation testing for code no mutation tool covers: apply each mutant
# from a list kept in the repo, run the tests, undo it, and count a kill only
# for a mutant it can prove it ran.
#
#   scripts/mutants.sh [-f <list>] -- <test command ...>     default list: .ant/mutants
#
# The list, one mutant per -/+ pair, under the file it changes:
#
#   # comment
#   @@ src/clamp.py
#   - if x < 0:
#   + if x <= 0:
#
# The text after "- " must occur exactly once in the file; it is replaced
# literally (no regex) by the text after "+ ". Paths are relative to the
# directory this runs in.
#
# Exit 0 = every mutant killed ("mutants: N/N killed"), 1 = a mutant survived,
# 2 = it could not prove the run: a bad list, an anchor that is absent or not
# unique, a mutant that changes nothing, a suite red before mutating or after
# restoring, a test command that could not run (rc 126/127).
#
# Reach for the language's mutation tool first (mutmut, Stryker, PIT,
# cargo-mutants): it mutates the syntax tree, so it cannot apply a mutant to
# code that moved. This list is a second copy of the code and goes stale on a
# refactor -- which is why a missing anchor is an error, never a skip.
#
# Why it proves execution. A hand-rolled runner fails in the one direction no
# gauntlet sees: old-coder's demo counted kills for mutants it never ran (two
# same-size mutants written in the same second shared a bytecode cache). So:
#   - each mutant's content hash must differ from the original before the run;
#   - every write is a second after the last, so no two versions of a file
#     share an mtime (the cache key of Python's .pyc and most build tools),
#     and PYTHONDONTWRITEBYTECODE=1 is set;
#   - a test command that could not run (126/127) aborts the run instead of
#     scoring a kill.
# It cannot prove the tests import the file; a survivor is how that shows.
#
# The original is restored by a trap on exit, INT and TERM, and the restore
# is proven with cmp. Tests run in the background so an interrupt is handled
# at once rather than after the test finishes.
#
# The body is one brace group ending in exit, so bash reads it whole before it
# runs: an edit made meanwhile must not be read at the old byte offset.
{
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1

say_error() { echo "mutants: ERROR ($*)"; }
list=.ant/mutants
while [ "$#" -gt 0 ]; do
  case "$1" in
    -f) list="${2:-}"; shift 2 || { say_error "-f needs a file"; exit 2; } ;;
    --) shift; break ;;
    *) say_error "usage: scripts/mutants.sh [-f <list>] -- <test command ...>"; exit 2 ;;
  esac
done
[ "$#" -gt 0 ] || { say_error "no test command after --"; exit 2; }
[ -f "$list" ] || { say_error "no mutant list at $list"; exit 2; }

T="$(mktemp -d)" || { say_error "cannot create a temp directory"; exit 2; }
files=() olds=() news=() originals=()
child=""

# Occurrences of $2 in file $1, literal. ENVIRON, not -v: -v interprets
# backslash escapes and would count a different string.
count() { PAT="$2" awk 'BEGIN { p = ENVIRON["PAT"]; n = 0 }
  { s = $0; while ((i = index(s, p)) > 0) { n++; s = substr(s, i + length(p)) } }
  END { print n }' "$1"; }

# Replace the one occurrence of $2 in file $1 with $3, literally.
apply() { OLD="$2" NEW="$3" awk 'BEGIN { o = ENVIRON["OLD"]; r = ENVIRON["NEW"]; done = 0 }
  { if (!done && (i = index($0, o)) > 0) { $0 = substr($0, 1, i - 1) r substr($0, i + length(o)); done = 1 } print }' \
  "$1" > "$T/apply" && cat "$T/apply" > "$1"; }

backup_of() {  # <file> -> the path of its backup
  local i
  # bash 3.2 under set -u calls an empty array unbound.
  [ "${#originals[@]}" -gt 0 ] || return 1
  for i in "${!originals[@]}"; do [ "${originals[$i]}" = "$1" ] && { echo "$T/orig.$i"; return 0; }; done
  return 1
}

restore_all() {  # every file back to its backup; 1 when one could not be proven restored
  local i rc=0
  [ "${#originals[@]}" -gt 0 ] || return 0
  for i in "${!originals[@]}"; do
    # Never write without the backup in hand: `cat <missing> > file` would
    # truncate the original to nothing.
    [ -f "$T/orig.$i" ] || { echo "  ✗ no backup of ${originals[$i]} -- left as it is"; rc=1; continue; }
    cmp -s "$T/orig.$i" "${originals[$i]}" || cat "$T/orig.$i" > "${originals[$i]}"
    cmp -s "$T/orig.$i" "${originals[$i]}" || { echo "  ✗ ${originals[$i]} could not be restored -- the original is in $T/orig.$i"; rc=1; }
  done
  return "$rc"
}

on_signal() {
  [ -n "$child" ] && kill "$child" 2>/dev/null
  restore_all || { echo "mutants: ERROR (interrupted, and a file was not restored)"; exit 2; }
  echo "mutants: ERROR (interrupted; every file restored)"
  exit 2
}
trap on_signal INT TERM
# The temp directory holds the backups, so only this last trap removes it, and
# only once every file is proven restored.
trap 'restore_all >/dev/null && rm -rf "$T"' EXIT

run_tests() {  # <log> <command ...> -> the command's exit status
  local log="$1"; shift
  "$@" < /dev/null > "$log" 2>&1 &
  child=$!
  wait "$child"
  local rc=$?
  child=""
  return "$rc"
}

# ---------------------------------------------------------------- the list
n=0 cur="" pending=0 old=""
while IFS= read -r line || [ -n "$line" ]; do
  n=$((n + 1))
  case "$line" in
    ""|\#*) continue ;;
    "@@ "*)
      [ "$pending" -eq 0 ] || { say_error "$list:$n: a '- ' line has no '+ ' line"; exit 2; }
      cur="${line#@@ }"
      [ -f "$cur" ] || { say_error "$list:$n: no file $cur"; exit 2; }
      backup_of "$cur" >/dev/null || {
        i="${#originals[@]}"; originals+=("$cur"); cp -p "$cur" "$T/orig.$i" || { say_error "cannot back up $cur"; exit 2; }; } ;;
    "- "*)
      [ -n "$cur" ] || { say_error "$list:$n: a mutant before any '@@ <file>' line"; exit 2; }
      [ "$pending" -eq 0 ] || { say_error "$list:$n: a '- ' line has no '+ ' line"; exit 2; }
      old="${line#- }"; pending=1
      [ -n "$old" ] || { say_error "$list:$n: an empty anchor"; exit 2; } ;;
    "+ "*|"+")
      [ "$pending" -eq 1 ] || { say_error "$list:$n: a '+ ' line with no '- ' line before it"; exit 2; }
      new="${line#+}"; new="${new# }"
      [ "$new" != "$old" ] || { say_error "$list:$n: the mutant changes nothing"; exit 2; }
      files+=("$cur"); olds+=("$old"); news+=("$new"); pending=0 ;;
    *) say_error "$list:$n: expected '@@ <file>', '- <text>' or '+ <text>'"; exit 2 ;;
  esac
done < "$list"
[ "$pending" -eq 0 ] || { say_error "$list: the last '- ' line has no '+ ' line"; exit 2; }
total="${#files[@]}"
[ "$total" -gt 0 ] || { say_error "$list has no mutants"; exit 2; }
for i in "${!files[@]}"; do
  c="$(count "${files[$i]}" "${olds[$i]}")"
  [ "$c" = 1 ] || { say_error "'${olds[$i]}' occurs $c times in ${files[$i]}, need exactly 1 -- the list is stale or the anchor too short"; exit 2; }
done

# ---------------------------------------------------------------- baseline
run_tests "$T/baseline.log" "$@"; rc=$?
case "$rc" in
  0) ;;
  126|127) say_error "the test command could not run (rc $rc): $(tail -1 "$T/baseline.log")"; exit 2 ;;
  *) say_error "the suite is red before any mutant (rc $rc) -- a red suite kills every mutant"; tail -5 "$T/baseline.log" | sed 's/^/    /'; exit 2 ;;
esac

# ---------------------------------------------------------------- mutants
killed=0 survivors=""
for i in "${!files[@]}"; do
  f="${files[$i]}" o="${olds[$i]}" w="${news[$i]}"
  b="$(backup_of "$f")"
  label="$f: '$o' -> '$w'"
  sleep 1; apply "$f" "$o" "$w" || { say_error "could not write $f"; exit 2; }
  if cmp -s "$b" "$f"; then say_error "$label: the file did not change"; exit 2; fi
  run_tests "$T/m$i.log" "$@"; rc=$?
  sleep 1; cat "$b" > "$f"
  cmp -s "$b" "$f" || { say_error "$f was not restored after $label"; exit 2; }
  case "$rc" in
    0) echo "  SURVIVED          $label"; survivors="${survivors:+$survivors; }$label" ;;
    126|127) say_error "the test command could not run (rc $rc) under $label"; exit 2 ;;
    *) echo "  killed   (rc $rc)  $label"; killed=$((killed + 1)) ;;
  esac
done

# ---------------------------------------------------------------- after
restore_all || { echo "mutants: ERROR (a file was not restored)"; exit 2; }
run_tests "$T/after.log" "$@" || { say_error "the suite is red after restoring every file"; exit 2; }

if [ "$killed" -eq "$total" ]; then
  echo "mutants: $killed/$total killed (each applied by content hash, a distinct mtime per write, suite green before and after)"
  exit 0
fi
echo "mutants: FAILED ($killed/$total killed; survivors: $survivors)"
exit 1
}
