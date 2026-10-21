#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Self-contained test for the job-output starter kit.  bash <this file>
#
# Self-contained on purpose: it copies the template beside itself into a temp
# tree and exercises it there, so it proves the kit works as SHIPPED rather
# than as wired into whatever repo it happens to be sitting in. That is also
# what lets the authoring repo's own gate run it (`git ls-files '*.test.sh'`)
# and keep the template from rotting.
#
# The exit-status assertion is the one that matters most: a wrapper that
# swallows a failure is worse than no wrapper, because the caller then holds a
# green light that was never earned.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(mktemp -d)"
# The teardown must not be able to overwrite the verdict, and it could: a
# supervisor still writing its .rc raced `rm -rf`, which failed with
# "Directory not empty", so this script printed `38 passed, 0 failed` and then
# exited 1 -- the exact shape the kit exists to prevent, inside its own test.
# Measured 2026-09-24: 1 run in 12, and it is what a freshly unpacked tarball
# happened to hit. The leaks that caused it are fixed where they were caused
# (every `run` below is now followed by a `wait`, because a job is not finished
# until its .rc exists); this makes a future one impossible to mistake for a
# failed assertion, and says so on its own line rather than swallowing it.
_teardown() {
  local rc=$?
  rm -rf "$ROOT" 2>/dev/null \
    || echo "teardown: $ROOT survived -- something was still writing into it" >&2
  exit "$rc"
}
trap _teardown EXIT
mkdir -p "$ROOT/scripts" "$ROOT/.ant"
cp "$SRC/lib-job-output.sh" "$SRC/logged.sh" "$SRC/detach.sh" "$ROOT/scripts/"
# logs_dir moves every sink and keeps the paths below it; the kit reads it from
# .ant/config by itself, with no plugin in sight.
# @S-runtime-dirs-003
# @N-runtime-dirs-002
printf 'logs_dir=logs\n' > "$ROOT/.ant/config"
chmod +x "$ROOT/scripts/logged.sh" "$ROOT/scripts/detach.sh"

pass=0 fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n     %s\n' "$1" "$2"; }

L="$ROOT/scripts/logged.sh"; D="$ROOT/scripts/detach.sh"

# --- the property the whole kit exists for ----------------------------------
rc=0; out="$("$L" okjob -- bash -c 'echo hello; exit 0' 2>&1)" || rc=$?
[ "$rc" = 0 ] && ok "a succeeding command returns 0" || bad "a succeeding command returns 0" "rc=$rc"

rc=0; "$L" badjob -- bash -c 'echo noise; exit 42' >/dev/null 2>&1 || rc=$?
[ "$rc" = 42 ] \
  && ok "a failing command's OWN status comes back, not the wrapper's" \
  || bad "a failing command's OWN status comes back, not the wrapper's" "rc=$rc"

# --- nothing is lost, it is only moved --------------------------------------
grep -qx hello "$ROOT/logs/logged/okjob.log" 2>/dev/null \
  && ok "stdout is in the log" || bad "stdout is in the log" "missing"
"$L" errjob -- bash -c 'echo boom >&2; exit 0' >/dev/null 2>&1
grep -qx boom "$ROOT/logs/logged/errjob.log" 2>/dev/null \
  && ok "stderr is in the log too" || bad "stderr is in the log too" "missing"

big="$("$L" quiet -- bash -c 'for i in $(seq 1 500); do echo "line $i"; done' 2>&1)"
[ "$(printf '%s' "$big" | wc -l)" -lt 5 ] \
  && ok "500 lines do not reach the terminal" \
  || bad "500 lines do not reach the terminal" "got $(printf '%s' "$big" | wc -l)"
[ "$(wc -l < "$ROOT/logs/logged/quiet.log")" -eq 500 ] \
  && ok "all 500 are in the log" || bad "all 500 are in the log" "short"

# --- neither a success nor a failure may be silent --------------------------
# `case`, not `printf | grep -q`. Same rule as the fourth CLAUDE.md line this
# kit installs -- never let a pipeline stand between a thing and the status you
# read back -- applied to the near side: under `set -o pipefail` the status is
# the WHOLE pipeline's, so `grep -q` closing the pipe early can fail the left
# half, and a suite that reports a marker as absent while printing that same
# marker in its own failure message is unreadable. It matters most at the
# negative assertion below, where && and || are inverted: there a failing
# pipeline reports "nothing leaked", which is the shape this kit exists to
# remove. `case` needs no subprocess and no pipe, and every pattern here is a
# literal string.
case "$big" in
  *✓*) ok "a successful run says so" ;;
  *)   bad "a successful run says so" "got: [$big]" ;;
esac
out="$("$L" loud -- bash -c 'echo FATAL-MARKER; exit 3' 2>&1)" || true
case "$out" in
  *FATAL-MARKER*) ok "on failure the tail is shown without being asked" ;;
  *)              bad "on failure the tail is shown without being asked" "got: [$out]" ;;
esac

# --- progress ----------------------------------------------------------------
# Driven from a script FILE: run_logged echoes the command line, so an inline
# `bash -c` would put its own text on the terminal and the negative assertion
# below would be reading that echo instead of the stream.
cat > "$ROOT/noisy.sh" <<'N'
echo plain-chatter
echo "== phase one"
N
out="$("$L" prog --progress '^== ' -- bash "$ROOT/noisy.sh" 2>&1)" || true
case "$out" in
  *"phase one"*) ok "lines matching --progress reach the terminal" ;;
  *)             bad "lines matching --progress reach the terminal" "got: [$out]" ;;
esac
# Inverted on purpose, and the reason `case` is used here rather than a pipe:
# a pipeline that fails for any reason at all would take the `ok` branch and
# report that nothing leaked.
case "$out" in
  *plain-chatter*) bad "lines that do not match stay in the log" "leaked" ;;
  *)               ok "lines that do not match stay in the log" ;;
esac

# --- and the display must not disarm its CALLER ------------------------------
# follow_matching is public API and opens with `set +e`. `set` is shell-global,
# not function-local, so defining it with { } left a FOREGROUND caller's
# errexit off for good -- a kit about failures not passing silently, silently
# turning off the thing that stops on failure. Two halves on purpose: a
# non-zero status AND the line after `false` never printed.
: > "$ROOT/f.log"; : > "$ROOT/f.log.done"
rc=0
bash -c '
  set -Eeuo pipefail
  . "$1/lib-job-output.sh"
  follow_matching "$2" zzz-no-such-line >/dev/null
  false
  echo LEAKED' _ "$ROOT/scripts" "$ROOT/f.log" > "$ROOT/f.out" 2>&1 || rc=$?
if [ "$rc" -ne 0 ] && ! grep -q LEAKED "$ROOT/f.out"; then
  ok "a foreground follow_matching leaves the caller's errexit ON"
else
  bad "a foreground follow_matching leaves the caller's errexit ON" \
      "rc=$rc out=[$(cat "$ROOT/f.out")]"
fi

# --- the verdict is a FILE ----------------------------------------------------
"$D" run dj -- bash -c 'sleep 1; exit 7' >/dev/null 2>&1
rc=0; "$D" wait dj 30 >/dev/null 2>&1 || rc=$?
[ "$rc" = 7 ] && ok "detach wait exits with the JOB's status" \
              || bad "detach wait exits with the JOB's status" "rc=$rc"
[ "$(cat "$ROOT/logs/detach/dj.rc")" = 7 ] \
  && ok "the .rc file holds the answer" || bad "the .rc file holds the answer" "no rc"
st="$("$D" status 2>/dev/null)" || true
case "$st" in
  *"nothing running"*) ok "'nothing running' is said out loud, not implied by silence" ;;
  *)                   bad "'nothing running' is said out loud, not implied by silence" "got: [$st]" ;;
esac

# --- a signal to the pid file reaches the JOB, and the verdict survives -------
# .pid is the supervisor's -- something has to outlive the job to write .rc.
# Before the forward, killing it killed the bookkeeper and left the job
# orphaned with no .rc: losing the one file everything else in the kit reads.
# The job reaps its own child on the way out: the forward reaches the job, not
# its children, so without this every run of this suite leaves a sleep(1)
# behind with ppid 1 for 30s -- a kit whose fifth structural property is "every
# sink has a bound from day one" cannot leak a process per run of its own test.
# It also demonstrates the thing detach.sh's header asks of a job that forks.
"$D" run sig -- bash -c 'sleep 30 & trap "kill $! 2>/dev/null; exit 9" TERM; wait' >/dev/null 2>&1
sleep 1
kill -TERM "$(cat "$ROOT/logs/detach/sig.pid")" 2>/dev/null
rc=0; "$D" wait sig 20 >/dev/null 2>&1 || rc=$?
[ "$rc" = 9 ] && [ "$(cat "$ROOT/logs/detach/sig.rc" 2>/dev/null)" = 9 ] \
  && ok "a signal to the pid file reaches the job, and .rc is still written" \
  || bad "a signal to the pid file reaches the job, and .rc is still written" \
        "wait=$rc file=$(cat "$ROOT/logs/detach/sig.rc" 2>/dev/null)"

# --- the sink is bounded, and an UNFINISHED job is never swept ----------------
: > "$ROOT/logs/detach/old.rc"; : > "$ROOT/logs/detach/old.log"
touch -t 202001010000 "$ROOT/logs/detach/old.rc" "$ROOT/logs/detach/old.log"
: > "$ROOT/logs/detach/orphan.log"          # no .rc == still running, or died
touch -t 202001010000 "$ROOT/logs/detach/orphan.log"
"$D" run sweeper -- true >/dev/null 2>&1; "$D" wait sweeper 30 >/dev/null 2>&1 || true
[ ! -f "$ROOT/logs/detach/old.rc" ] \
  && ok "a finished job past the window is swept" || bad "a finished job past the window is swept" "kept"
[ -f "$ROOT/logs/detach/orphan.log" ] \
  && ok "a job with no .rc is KEPT -- that is evidence, not litter" \
  || bad "a job with no .rc is KEPT -- that is evidence, not litter" "swept"

# --- every artefact goes, and the sweep does not take its caller down ---------
# `<name>.<key>` is not a job's only file: logged leaves `<name>.log.done` and
# detach can leave `<name>.rc.tmp`. A narrower sweep that removed only the
# files whose base is exactly `<name>` kept those for ever -- and because the
# per-file test was the LAST command of its loop, sweep_stale_logs returned 1
# and errexit took the caller with it: `logged.sh` exiting 1 with no output at
# all. Both halves are asserted: the leftovers check passes on its own while
# the caller is being killed, and the rc check passes on its own while the
# directory fills up.
# Named to sort LAST among the .rc files here, and that is load-bearing: a
# function returns the status of its last command, so an inner loop that fails
# for a base in the MIDDLE is discarded by the next outer iteration's
# `continue`. With any other name this assertion passes while the bug is
# present -- the same way `orphan` shared no prefix with `old` and hid the one
# above it.
: > "$ROOT/logs/detach/zsib.rc"; : > "$ROOT/logs/detach/zsib.log"
: > "$ROOT/logs/detach/zsib.pid"; : > "$ROOT/logs/detach/zsib.rc.tmp"
touch -t 202001010000 "$ROOT/logs/detach"/zsib.*
rc=0; "$D" run sweeper2 -- true >/dev/null 2>&1 || rc=$?
"$D" wait sweeper2 20 >/dev/null 2>&1 || true   # a job is done when its .rc is
[ "$rc" = 0 ] && ok "a sweep with work to do does not fail its caller" \
              || bad "a sweep with work to do does not fail its caller" "rc=$rc"
# tr: BSD wc pads its count with spaces.
left="$(find "$ROOT/logs/detach" -maxdepth 1 -name 'zsib.*' | wc -l | tr -d ' ')"
[ "$left" = 0 ] \
  && ok "every artefact of a swept job goes, not just <name>.<key>" \
  || bad "every artefact of a swept job goes, not just <name>.<key>" "left=$left"

# --- the name set that sweep depends on --------------------------------------
# A dot in a name makes `"$base".*` in sweep_stale_logs reach into a DIFFERENT
# job: a finished `build` deleted a running `build.api`'s .pid and .log, and
# `wait build.api` then said "nothing started as" about a job pgrep could see.
# Refused at the door instead, in both entry points, from one ERE in the
# library -- two copies of it would drift, and it is what the sweep relies on.
rc=0;  "$D" run build.api -- true >/dev/null 2>&1 || rc=$?
rc2=0; "$L" build.api     -- true >/dev/null 2>&1 || rc2=$?
[ "$rc" = 2 ] && [ "$rc2" = 2 ] \
  && ok "a name with a dot is refused by both entry points" \
  || bad "a name with a dot is refused by both entry points" "detach=$rc logged=$rc2"
# The control: without it, refusing EVERY name would pass the assertion above.
rc=0; "$L" a_b-1 -- true >/dev/null 2>&1 || rc=$?
[ "$rc" = 0 ] && ok "letters, digits, _ and - are still a name" \
              || bad "letters, digits, _ and - are still a name" "rc=$rc"

# --- a job that never started is not "still running" -------------------------
# The launcher's own failure and a typo in the name reach `wait` the same way,
# and before this it answered both by sitting out the bound and then calling a
# job that never existed "still running". Bounded at 30s so a regression shows
# up as a red assertion rather than as this suite hanging.
sec=$SECONDS; rc=0
"$D" wait never-started-here 30 >/dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] && [ $((SECONDS - sec)) -lt 5 ] \
  && ok "wait on a name that was never run says so at once (exit 2)" \
  || bad "wait on a name that was never run says so at once (exit 2)" "rc=$rc after $((SECONDS - sec))s"

# --- the file tells the job's own 2 from the script's own 2 -------------------
# Both come back as 2 and nothing about the number says which is which: the
# script says 2 for a bad verb, a bad name and an unknown job, and a job is
# free to exit 2 as well. Picking other numbers does not fix that -- any number
# a job can exit with, it can collide with. The file is the test that cannot
# collide, which is the property this whole kit is built on, so it is asserted
# rather than left in a comment.
"$D" run two -- bash -c 'exit 2' >/dev/null 2>&1
rc=0; "$D" wait two 20 >/dev/null 2>&1 || rc=$?
rcx=0; "$D" wait no-such-job-here 5 >/dev/null 2>&1 || rcx=$?
[ "$rc" = 2 ] && [ "$rcx" = 2 ] \
  && [ "$(cat "$ROOT/logs/detach/two.rc" 2>/dev/null)" = 2 ] \
  && [ ! -f "$ROOT/logs/detach/no-such-job-here.rc" ] \
  && ok "the .rc file tells a job's own 2 from this script's own 2" \
  || bad "the .rc file tells a job's own 2 from this script's own 2" \
        "wait=$rc unknown=$rcx file=$(cat "$ROOT/logs/detach/two.rc" 2>/dev/null)"

# --- a job that does not trap the signal still leaves a verdict ---------------
# The other signal assertion uses a job that traps TERM and picks its own
# status. This one does not trap anything, which is the ordinary case, and the
# point is that the supervisor outlives it and records 128+15 instead of the
# whole thing vanishing. Its child is deliberately left behind -- the forward
# reaches the job, not its children (see detach.sh) -- so this cleans it up:
# a test suite that leaks a background process is the very thing being fixed.
"$D" run notrap -- bash -c 'sleep 30 & echo "gc=$!"; wait' >/dev/null 2>&1
sleep 1
kill -TERM "$(cat "$ROOT/logs/detach/notrap.pid")" 2>/dev/null
rc=0; "$D" wait notrap 20 >/dev/null 2>&1 || rc=$?
[ "$rc" = 143 ] && [ "$(cat "$ROOT/logs/detach/notrap.rc" 2>/dev/null)" = 143 ] \
  && ok "a job that does not trap the signal still leaves a verdict (143)" \
  || bad "a job that does not trap the signal still leaves a verdict (143)" \
        "wait=$rc file=$(cat "$ROOT/logs/detach/notrap.rc" 2>/dev/null)"
gc="$(sed -n 's/^gc=//p' "$ROOT/logs/detach/notrap.log" | head -1)"
[ -n "$gc" ] && kill -9 "$gc" 2>/dev/null || true

# --- shapes that must be refused ---------------------------------------------
rc=0; "$L" 'bad name' -- true >/dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] && ok "a name that is not a plain file name is refused" \
              || bad "a name that is not a plain file name is refused" "rc=$rc"
rc=0; "$L" noargs true >/dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] && ok "the command must follow --" || bad "the command must follow --" "rc=$rc"

# --- the platform this kit was WRONG about ------------------------------------
# A field report from an Ubuntu 18.04 fleet (util-linux 2.31.1, coreutils 8.28)
# found detach.sh dead there, and none of the assertions above could see it:
# they only ever run where the launcher already works. These two do not.
# It simulates an OLD setsid, so it needs a real one: macOS has none at all,
# and that case has its own assertions below.
# @N-detach-001
SHIM="$ROOT/shim"; mkdir -p "$SHIM"
REAL_SETSID="$(command -v setsid || true)"; REAL_ENV="$(command -v env)"
# The env shim needs no setsid: the no-perl case below uses it everywhere.
cat > "$SHIM/env" <<SH
#!$BASH
case "\${1:-}" in --default-signal*) echo "env: unrecognized option" >&2; exit 125 ;; esac
exec "$REAL_ENV" "\$@"
SH
chmod +x "$SHIM/env"
if [ -n "$REAL_SETSID" ]; then
cat > "$SHIM/setsid" <<SH
#!$BASH
[ "\$1" = "-f" ] && { echo "setsid: invalid option -- 'f'" >&2; exit 1; }
exec "$REAL_SETSID" "\$@"
SH
chmod +x "$SHIM/setsid"

rc=0
( PATH="$SHIM:$PATH"; "$D" run oldbox -- bash -c 'exit 7' ) >/dev/null 2>&1 || rc=$?
( PATH="$SHIM:$PATH"; "$D" wait oldbox 30 ) >/dev/null 2>&1 || true
[ "$(cat "$ROOT/logs/detach/oldbox.rc" 2>/dev/null)" = 7 ] \
  && ok "runs where neither 'setsid -f' nor 'env --default-signal' exists" \
  || bad "runs where neither 'setsid -f' nor 'env --default-signal' exists" "run_rc=$rc"
else
  echo "skip (no setsid here): the old-setsid simulation needs a real one to wrap"
fi

# --- macOS: no setsid binary, no /proc -----------------------------------------
# Measured 2026-10-20 on macOS 26.6.2: detach never started a job there. The
# /proc read died under errexit before the comment that handles "no /proc"
# could run, and the only fallback assumed a setsid without -f. A PATH that
# holds everything but the named tools is how they are genuinely absent.
pathless() {  # <dir> <tool>... -- a PATH directory with every tool but these
  local dir="$1" d f b skip; shift; mkdir -p "$dir"
  # Joined before IFS changes: under IFS=: "$*" would read "setsid:perl" and
  # exclude neither -- the helper would build the PATH it claims to remove.
  skip=" $* "
  local IFS=:
  for d in $PATH; do
    [ -d "$d" ] || continue
    for f in "$d"/*; do
      b="${f##*/}"
      case "$skip" in *" $b "*) continue ;; esac
      [ -x "$f" ] && [ ! -e "$dir/$b" ] && ln -s "$f" "$dir/$b"
    done
  done
  return 0
}
# @S-detach-001
pathless "$ROOT/nosetsid" setsid
rc=0; PATH="$ROOT/nosetsid" "$D" run nos -- bash -c 'exit 7' >/dev/null 2>&1 || rc=$?
wrc=0; PATH="$ROOT/nosetsid" "$D" wait nos 30 >/dev/null 2>&1 || wrc=$?
[ "$rc" = 0 ] && [ "$wrc" = 7 ] && [ "$(cat "$ROOT/logs/detach/nos.rc" 2>/dev/null)" = 7 ] \
  && ok "with no setsid binary at all (macOS), perl's setsid starts the job" \
  || bad "with no setsid binary at all (macOS), perl's setsid starts the job" "run=$rc wait=$wrc rc=$(cat "$ROOT/logs/detach/nos.rc" 2>/dev/null)"
# @S-detach-002
rc=0; out="$( trap '' HUP INT TERM; DETACH_PROC_STATUS="$ROOT/no-such-proc-status" "$D" run noproc -- bash -c 'exit 7' 2>&1 )" || rc=$?
"$D" wait noproc 30 >/dev/null 2>&1 || true
[ "$rc" = 0 ] && [ "$(cat "$ROOT/logs/detach/noproc.rc" 2>/dev/null)" = 7 ] \
  && ok "with no /proc (macOS, BSD) it takes the conservative branch and starts the job" \
  || bad "with no /proc (macOS, BSD) it takes the conservative branch and starts the job" "rc=$rc out=[$out]"
# The same case proven to read the named file: with nothing inherited as
# ignored and no perl, a real /proc lets the job start; a missing one must
# take the conservative branch, which needs perl, and refuse. env has to lack
# --default-signal too (as on macOS), or the file is never read at all.
pathless "$ROOT/noperl" perl env
cat > "$ROOT/noperl/env" <<SH
#!$BASH
case "\${1:-}" in --default-signal*) echo "env: unrecognized option" >&2; exit 125 ;; esac
exec "$(command -v env)" "\$@"
SH
chmod +x "$ROOT/noperl/env"
# Launched through perl with HUP/INT/TERM at their defaults: a runner that
# backgrounds this suite (mutants.sh does) hands it INT ignored, and then a
# real /proc would refuse too and the case could not tell the file was read.
rc=0; out="$( DETACH_PROC_STATUS="$ROOT/no-such-proc-status" perl -e '$SIG{HUP}=$SIG{INT}=$SIG{TERM}=q(DEFAULT); $ENV{PATH}=shift; exec @ARGV or die' "$ROOT/noperl" "$D" run noproc2 -- true 2>&1 )" || rc=$?
case "$out" in *Refusing*) refused=y ;; *) refused=n ;; esac
[ "$rc" = 4 ] && [ "$refused" = y ] \
  && ok "an unreadable status file is unknown, not \"nothing ignored\"" \
  || bad "an unreadable status file is unknown, not \"nothing ignored\"" "rc=$rc out=[$out]"
# @S-detach-003
# A status file saying nothing is inherited as ignored, so this reaches the
# launcher on every platform: without it, macOS (no /proc) refuses one step
# earlier for the dispositions, correctly but for a different reason.
pathless "$ROOT/bare" setsid perl
printf 'SigIgn:\t0000000000000000\n' > "$ROOT/status-nothing-ignored"
rc=0; out="$( DETACH_PROC_STATUS="$ROOT/status-nothing-ignored" PATH="$ROOT/bare" "$D" run bare -- true 2>&1 )" || rc=$?
case "$out" in *setsid*perl*|*perl*setsid*) named=y ;; *) named=n ;; esac
[ "$rc" = 4 ] && [ "$named" = y ] && [ ! -e "$ROOT/logs/detach/bare.pid" ] \
  && ok "with neither setsid nor perl it refuses (exit 4), names both, starts nothing" \
  || bad "with neither setsid nor perl it refuses (exit 4), names both, starts nothing" "rc=$rc out=[$out]"

# --- and where no fallback exists, it must SAY so, not start a trapless job ----
# Dispositions inherited as ignored, no --default-signal, and no perl to undo
# it. A minimal PATH is how perl is genuinely absent rather than pretend-absent.
MIN="$ROOT/min"; mkdir -p "$MIN"
for b in awk find rm mkdir cat sed mv touch sleep basename dirname bash; do
  src="$(command -v "$b")" && ln -sf "$src" "$MIN/$b"
done
cp "$SHIM/env" "$MIN/env"
out="$( trap '' HUP INT TERM; PATH="$MIN" "$MIN/bash" "$D" run trapless -- true 2>&1 )" && rc=0 || rc=$?
case "$out" in *Refusing*) saw_refusal=y ;; *) saw_refusal=n ;; esac
if [ "$rc" -eq 4 ] && [ "$saw_refusal" = y ]; then
  ok "with no way to restore dispositions it ABORTS and says why (exit 4)"
else
  bad "with no way to restore dispositions it ABORTS and says why (exit 4)" "rc=$rc out=[$out]"
fi

# --- the usage text is found by content, not by line number -------------------
# detach's `sed -n '4,6p'` printed a blank line and two of its three verbs:
# `status` was on line 7 and never reached the reader. logged's `3,4p` was
# worse -- the description and a blank line, never the usage line at all. The
# only reader of either is an error path, which is why nothing said so.
u="$("$D" zzz 2>&1 >/dev/null)" || true
case "$u" in
  *"detach.sh status"*) ok "detach usage names every verb it has" ;;
  *)                    bad "detach usage names every verb it has" "got: [$u]" ;;
esac
u2="$("$L" nm nodash 2>&1 >/dev/null)" || true
case "$u2" in
  *"logged.sh <name>"*) ok "logged usage prints the usage line" ;;
  *)                    bad "logged usage prints the usage line" "got: [$u2]" ;;
esac

# --- `status` with no name is not green when a job died ----------------------
# It printed DIED to stderr, "nothing running" to stdout and exited 0 -- the
# form you reach for to ask "is anything wrong" answering no where a caller
# reads. The named form already returned 125.
: > "$ROOT/logs/detach/zomb.log"; echo 2147483647 > "$ROOT/logs/detach/zomb.pid"
rc=0; sout="$("$D" status 2>/dev/null)" || rc=$?
[ "$rc" = 125 ] \
  && ok "status with no name exits 125 when a job died without one" \
  || bad "status with no name exits 125 when a job died without one" "rc=$rc"
case "$sout" in
  *"nothing running"*) bad "a died job is not announced as 'nothing running'" "said it" ;;
  *)                   ok "a died job is not announced as 'nothing running'" ;;
esac
rm -f "$ROOT/logs/detach/zomb.pid" "$ROOT/logs/detach/zomb.log"

# --- the bound is checked the way the name is --------------------------------
# `wait x abc` reached $(( )) and died as bash's own "abc: unbound variable",
# naming nothing; `wait x -5` put the deadline in the past and answered a
# confident 124 -- "still running after -5s" -- for a job it never waited for.
# 124 is one of detach.sh's own codes, so that was a verdict it had not earned.
# The third call is the control: a real bound must still reach the job's status.
rc=0;  "$D" wait dj abc >/dev/null 2>&1 || rc=$?
rc2=0; "$D" wait dj -5  >/dev/null 2>&1 || rc2=$?
rc3=0; "$D" wait dj 20  >/dev/null 2>&1 || rc3=$?
[ "$rc" = 2 ] && [ "$rc2" = 2 ] && [ "$rc3" = 7 ] \
  && ok "a bound that is not a number of seconds is refused, and a real one still works" \
  || bad "a bound that is not a number of seconds is refused, and a real one still works" \
        "abc=$rc neg=$rc2 real=$rc3"

# --- a launcher that fails is REPORTED, not returned as its own status -------
# cmd_run's paragraph says this was fixed, and on one of its two launch paths it
# was not: the `setsid -f` call was bare under errexit, so a launcher exiting
# non-zero ended cmd_run before its own pid-file check and `run` left with the
# LAUNCHER's status and an empty terminal. The other branch backgrounds a
# subshell, which always succeeds, so it always reached the check -- and the two
# fallback assertions above plus the legacy-userland CI job only ever take THAT
# one, which is why nothing here could see it. Measured 2026-09-24: rc=99, no
# output. The shim lets the capability probe through and refuses the real call.
LF="$ROOT/lfshim"; mkdir -p "$LF"
cat > "$LF/setsid" <<SH
#!$BASH
[ "\$*" = "-f true" ] && exit 0
echo "shim setsid: refusing to launch" >&2
exit 99
SH
chmod +x "$LF/setsid"
rc=0; out="$(PATH="$LF:$PATH" "$D" run lfjob -- true 2>&1)" || rc=$?
case "$out" in *"did not start"*) said=y ;; *) said=n ;; esac
[ "$rc" = 5 ] && [ "$said" = y ] \
  && ok "a failing launcher is reported and exits 5, not its own status" \
  || bad "a failing launcher is reported and exits 5, not its own status" "rc=$rc out=[$out]"

# --- ...and the job it never started is not "still running" -------------------
# Same state, three verbs, three different answers before this: run 99 in
# silence, wait a confident 124 after sitting out the WHOLE bound, status 2.
# The bound is 30 so a regression is a red assertion, not a slow suite.
sec=$SECONDS; rcw=0
"$D" wait lfjob 30 >/dev/null 2>&1 || rcw=$?
[ "$rcw" = 2 ] && [ $((SECONDS - sec)) -lt 5 ] \
  && ok "wait says nothing started for a job whose launcher failed (exit 2)" \
  || bad "wait says nothing started for a job whose launcher failed (exit 2)" \
        "rc=$rcw after $((SECONDS - sec))s"
rcs=0; sout="$("$D" status lfjob 2>&1)" || rcs=$?
case "$sout" in *"lfjob.log"*) named=y ;; *) named=n ;; esac
[ "$rcs" = "$rcw" ] && [ "$rcs" = 2 ] && [ "$named" = y ] \
  && ok "wait and status answer that state alike, and status names the log" \
  || bad "wait and status answer that state alike, and status names the log" \
        "wait=$rcw status=$rcs named=$named out=[$sout]"

# --- replacing the log of a job that died without a status is said out loud ---
# `status` answers 125 and names that log; running the name again is the next
# thing a reader does, and it used to take the only copy of it without a word --
# while sweep_stale_logs deliberately keeps exactly that file. The fixture is
# the same shape as the zomb one above: a pid nothing can be, so no process is
# involved and nothing is left behind.
printf 'FIRST-RUN-EVIDENCE\n' > "$ROOT/logs/detach/dyer.log"
echo 2147483647 > "$ROOT/logs/detach/dyer.pid"
out="$("$D" run dyer -- true 2>&1)" || true
"$D" wait dyer 20 >/dev/null 2>&1 || true       # ...here too
case "$out" in
  *"died without a status"*) ok "replacing a dead job's log is said out loud" ;;
  *) bad "replacing a dead job's log is said out loud" "got: [$out]" ;;
esac

# --- the same name twice, sequentially, is refused ----------------------------
# 3 is in detach.sh's header and the gate in ci-checks.sh requires every code it
# can return to be there -- but nothing exercised it, and a documented code with
# no test is how 3 came to be MISSING from that header for a round. Concurrently
# the guard catches nothing (measured; see the comment beside it); this is the
# case it does catch. The TERM at the end reaches the job through the
# supervisor, which is the forwarding two assertions above already prove, so
# this leaves no process behind.
"$D" run liveone -- bash -c 'sleep 20' >/dev/null 2>&1
rc=0; "$D" run liveone -- true >/dev/null 2>&1 || rc=$?
[ "$rc" = 3 ] \
  && ok "a second run of a live name is refused (exit 3)" \
  || bad "a second run of a live name is refused (exit 3)" "rc=$rc"
# Collect the verdict rather than just sending the signal: `kill` returns as
# soon as the signal is sent, and the supervisor then forwards it, reaps the
# job and writes .rc -- into the directory the EXIT trap is about to remove.
# This is the same "a stream is not the answer, the file is" the kit is named
# for, applied to its own teardown.
kill "$(cat "$ROOT/logs/detach/liveone.pid")" 2>/dev/null || true
"$D" wait liveone 20 >/dev/null 2>&1 || true

# --- wait hands back what the job said, so reading it is not another turn ----
# 2026-09-28: `wait` said only "exited 2" and the next tool call was always a
# grep for WHICH lane went red -- an extra round trip that re-sends the whole
# context, costing more than the output this kit keeps out of it. The lane lines
# were in <name>.log all along. A finished job's log is shown whole when it is
# short (a logged.sh surface: progress lines, the failure tail, the verdict),
# its tail when it is long; a running one shows its latest line only.
"$D" run shortred -- bash -c 'echo "lane a (rc=0)"; echo "lane b (rc=1)"; for i in $(seq 1 30); do echo "tail $i"; done; exit 1' >/dev/null 2>&1
out="$("$D" wait shortred 30 2>&1)" || true
case "$out" in
  *"lane a (rc=0)"*"lane b (rc=1)"*"tail 30"*) ok "wait shows a short finished log whole, lane lines included" ;;
  *) bad "wait shows a short finished log whole, lane lines included" "got: [$out]" ;;
esac
"$D" run longlog -- bash -c 'for i in $(seq 1 500); do echo "line $i"; done' >/dev/null 2>&1
out="$("$D" wait longlog 30 2>&1)" || true
if printf '%s\n' "$out" | grep -qE '^ *line 500$' \
   && ! printf '%s\n' "$out" | grep -qE '^ *line (1|475)$' \
   && printf '%s\n' "$out" | grep -q '500 lines'; then
  ok "wait shows only the tail of a long log, and says how long it is"
else
  bad "wait shows only the tail of a long log, and says how long it is" "got: [$(printf '%s' "$out" | head -5)]"
fi
"$D" run inflight -- bash -c 'echo "stage one"; echo "stage two"; sleep 30' >/dev/null 2>&1
sleep 1
out="$("$D" wait inflight 1 2>&1)" || true
case "$out" in
  *"stage one"*) bad "wait on a running job shows its latest line only" "got: [$out]" ;;
  *"stage two"*) ok "wait on a running job shows its latest line only" ;;
  *) bad "wait on a running job shows its latest line only" "got: [$out]" ;;
esac
kill "$(cat "$ROOT/logs/detach/inflight.pid")" 2>/dev/null || true
"$D" wait inflight 20 >/dev/null 2>&1 || true

echo; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
