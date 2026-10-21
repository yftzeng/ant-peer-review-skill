#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# The one way to start a job that must outlive a command timeout.
#
#   scripts/detach.sh run    <name> -- <command> [args...]
#   scripts/detach.sh wait   <name> [seconds]   # its output, then the JOB's status
#   scripts/detach.sh status [<name>]           # no name: what is still running
#
# Writes $DETACH_DIR/<name>.log, .rc (written LAST) and .pid.
#
# .pid holds the SUPERVISOR, not the job: something has to outlive the job to
# write .rc. HUP/INT/TERM sent to it are forwarded to the job, so
# `kill -TERM $(cat <name>.pid)` does what it reads like -- before that it
# killed the bookkeeper and left the job orphaned with no verdict at all,
# losing the one file everything else here reads.
#
# It reaches the job process, NOT its children: a job that forks leaves those
# behind (measured -- the verdict is still written, the grandchild lives on).
# Signalling the process group instead would reach them and take the supervisor
# with it, losing the .rc, which is the thing this exists to protect. If the job
# owns children, it is the job that has to forward -- `trap ... TERM` in it.
# wait exits with the JOB's own status. Everything this script says itself:
#   2   bad verb, bad name, bad bound, a missing `--`, or no job by that name
#       -- which now includes a name whose launcher never got it started
#   3   that name is still running -- a second one is not started (run)
#   4   refused to launch: no way to restore signal dispositions, or no
#       way (setsid, perl) to give the job a session of its own
#   5   the launcher failed; the job never started (run)
#   124 still running when the bound ran out (wait)
#   125 died without writing a status (wait, status)
# Those are small integers, so a JOB that exits 2, 3, 4, 5, 124 or 125 is
# indistinguishable from them BY EXIT STATUS ALONE. That is not fixable by
# picking other numbers -- any number a job can exit with, it can collide with.
# The test that cannot collide is the file, which is the whole point of this
# kit: `.rc` exists => the status is the job's, and its content IS that status.
# `.rc` absent => the number came from the list above.
#
# Why not `nohup cmd &`: nohup IGNORES SIGHUP, an ignored signal is inherited
# across fork and exec, and bash cannot trap a signal it starts with ignored --
# so every `trap ... HUP` inside the job silently stops existing. Here the job
# gets default dispositions back and its own session, which is the part nohup
# was reached for: a timeout that kills the caller's process group cannot
# reach it.
#
# Why not `pgrep -f` to ask whether it is done: it matches its own command
# line. The .rc file is the answer.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./lib-job-output.sh
. "$REPO/scripts/lib-job-output.sh"

DETACH_DIR="${DETACH_DIR:-$(ant_logs_dir "$REPO")/detach}"
# Found by content, not by line number: `sed -n '4,6p'` printed a blank line
# and two of the three verbs -- `status` sat on line 7 and never reached the
# reader -- and nothing would have said so the next time this header grew.
usage() { sed -n '/^#   scripts\//p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; }

_name() {
  # One ERE, in the library: the sweep's correctness depends on it (see there).
  [[ "${1:-}" =~ $JOB_NAME_ERE ]] || {
    echo "detach: '${1:-}' is not a plain name (letters, digits, _ and - only)" >&2; exit 2; }
  LOG="$DETACH_DIR/$1.log"; RC="$DETACH_DIR/$1.rc"; PIDF="$DETACH_DIR/$1.pid"
}
_alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

# The two properties this script exists for, and where they come from:
#   A) the job gets its OWN SESSION, so a timeout that kills the caller's
#      process group cannot reach it;
#   B) the job gets DEFAULT SIGNAL DISPOSITIONS, so every `trap` inside it is
#      real (see the nohup note above).
# `setsid -f` (util-linux >= 2.32) and `env --default-signal` (coreutils >=
# 8.32) are the direct way to get them, and an earlier version of this file
# wrote them down as the REQUIREMENT. That was the implementation mistaken for
# the need. Measured 2026-09-23 across four userlands: Ubuntu 18.04 has
# util-linux 2.31.1 and coreutils 8.28 and has NEITHER, while Debian 10 has
# `setsid -f` but not `--default-signal` -- the two thresholds differ, so a
# machine can have one half. Each half therefore has a fallback that was
# tested against a control group, and where no fallback exists this ABORTS
# rather than start a job that silently has no traps.
_reset_prefix() {
  RESET=()
  if env --default-signal=HUP true 2>/dev/null; then
    RESET=(env "--default-signal=HUP,INT,TERM"); return 0
  fi
  local ign v
  # `|| true`: without it the failing read ended the script right here under
  # errexit, on exactly the platforms the next lines exist for (measured on
  # macOS 26.6.2: no job ever started). DETACH_PROC_STATUS points the read at
  # another file, so a test can take this branch where /proc exists.
  ign="$(awk '/^SigIgn:/{print $2}' "${DETACH_PROC_STATUS:-/proc/self/status}" 2>/dev/null || true)"
  # No /proc (macOS, BSD) means we cannot ask, and `$((16#))` on the empty
  # string dies with a bash arithmetic error that names nothing about the
  # cause. Unknown takes the conservative branch, it does not guess.
  [ -n "$ign" ] || ign=ffffffffffffffff
  v=$((16#$ign))
  # HUP=bit0 INT=bit1 TERM=bit14. Nothing inherited ignored -> nothing to undo,
  # and saying so beats installing a no-op that looks load-bearing.
  if [ $(( ((v>>0)&1) | ((v>>1)&1) | ((v>>14)&1) )) -eq 0 ]; then return 0; fi
  if command -v perl >/dev/null 2>&1; then
    # LC_ALL=C: perl's locale warning would otherwise be the job log's head.
    RESET=(env LC_ALL=C perl -e '$SIG{HUP}=$SIG{INT}=$SIG{TERM}=q(DEFAULT); exec @ARGV')
    return 0
  fi
  echo "detach: HUP/INT/TERM are inherited as IGNORED (SigIgn=$ign), and this" >&2
  echo "        platform has neither 'env --default-signal' nor perl to undo" >&2
  echo "        it. Every trap inside the job would silently not exist." >&2
  echo "        Refusing -- a launcher that quietly loses traps is worse than" >&2
  echo "        no launcher." >&2
  exit 4
}

cmd_run() {
  _name "${1:-}"; local name="$1"; shift
  if [ "${1:-}" != "--" ] || [ $# -lt 2 ]; then usage; exit 2; fi
  shift
  mkdir -p "$DETACH_DIR"
  # Keyed on `rc`, so ONLY finished jobs are swept.
  sweep_stale_logs "$DETACH_DIR" rc
  # Two runs of the same name racing each other BOTH get past this. Measured
  # twenty concurrent double-submits, on two machines: the guard caught 0 of 20
  # both times, and 20 of 20 ended with a single `.rc` holding ONE of the two
  # verdicts -- the other is destroyed. Those two are the property, and both
  # are deterministic. The visible symptom, `mv: cannot stat '<name>.rc.tmp'`
  # in the log, is NOT: 20 of 20 and then 18 of 20 on the SAME machine two
  # hours apart, and 15 of 20 on the other, because it needs both supervisors
  # to reach the rename. (The first of those three was written in here as a
  # property last round. It was a sample.) Do not read
  # that line's count as a count of the defect -- and do not read a run without
  # it as the guard having worked. Sequentially the guard IS correct (rc=3),
  # which is asserted in the suite: a documented code with no test is how `3`
  # came to be missing from the list above in the first place.
  # Deliberately not fixed: every portable lock (a claim file, a lock
  # directory) is new state that needs its own staleness rule, and a crashed
  # runner would then wedge that name for ever -- which is a maintainer's
  # decision, not a thing to slip in here. Do NOT "tidy" it by giving the temp
  # file a unique name: both `mv`s would then succeed, one verdict would still
  # be lost, and that error line is currently the only evidence it happened.
  if [ ! -f "$RC" ] && _alive; then
    echo "detach: '$name' is still running (pid $(cat "$PIDF"))" >&2; exit 3
  fi
  # A job that died without a verdict is the evidence `sweep_stale_logs` keeps
  # on purpose for $JOB_KEEP_DAYS, and `status` names THIS log when it answers
  # 125 -- so running the name again is the very next thing a reader does, and
  # the line below used to take the only copy without a word. Not moved aside
  # to `<name>.log.died`: the sweep is keyed on `.rc`, so nothing would ever
  # remove that, and an unbounded directory is what this kit exists to avoid.
  # Saying it out loud is the whole fix.
  if [ ! -f "$RC" ] && [ -f "$LOG" ] && [ -f "$PIDF" ]; then
    echo "detach: replacing the log of '$name', which died without a status" >&2
  fi
  rm -f "$LOG" "$RC" "$RC.tmp" "$PIDF"
  _reset_prefix
  # One copy of the body: two copies of it would drift.
  # rc via temp+rename so a reader never sees half a number. "$@" runs without
  # errexit on purpose: its status is the answer.
  local body='
    pidf=$1 rcf=$2; shift 2
    # The job goes to the background and the supervisor forwards signals to it,
    # so `kill -TERM $(cat <name>.pid)` does what it reads like. Before this it
    # killed the bookkeeper and left the job orphaned with NO .rc at all --
    # losing the one file everything else in this kit reads.
    "$@" &
    job=$!
    for s in HUP INT TERM; do trap "intr=1; kill -$s $job 2>/dev/null" "$s"; done
    # The pid file is published only once forwarding is armed. Written before,
    # there is a window where the caller can read it and signal a supervisor
    # whose handlers are not installed yet -- which is the very bug above,
    # narrowed rather than closed.
    echo $$ > "$pidf"
    # An interrupted `wait` returns 128+n, which is NOT the job status, and it
    # does not reap the child, so waiting again yields the real one. The flag is
    # what distinguishes the two cases: `kill -0 "$job"` here would race the job
    # exiting and record 143 for a job that exited 9, and a wrapper that reports
    # the wrong status is the one thing this kit must not do.
    # No guard is needed for "the trap fired just after a successful wait":
    # bash REMEMBERS the status of a reaped child indefinitely, so waiting a
    # second time returns that same value rather than 127 (measured 2026-09-24:
    # 9 -> 9 -> 9, and 143 -> 143; 127 is only ever for a pid that was never a
    # child of this shell). NOTE: no apostrophes in here -- this whole block
    # lives inside a single-quoted string, and bash single quotes have no
    # escape, so one would end the string. shellcheck SC1011 catches it.
    # A reviewer added such a guard, could not provoke it in 80 timed trials,
    # measured the mechanism, and removed it -- recorded here so the next one
    # does not add it back.
    while :; do
      intr=
      wait "$job"; rc=$?
      [ -n "$intr" ] || break
    done
    echo "$rc" > "$rcf.tmp" && mv "$rcf.tmp" "$rcf"
  '
  # `|| lrc=$?` is load-bearing on the first branch: it was a bare call under
  # errexit, so a launcher that exits non-zero ended this function HERE, before
  # the pid-file check below -- and `run` left with the LAUNCHER's status and an
  # empty terminal, which is exactly what the paragraph below says was fixed.
  # It was fixed on the second branch only: a backgrounded subshell always
  # succeeds, so that one always reached the check. The suite's two fallback
  # assertions and the legacy-userland job only ever take that branch, so
  # nothing here could see it. Measured 2026-09-24 with a setsid that passes
  # the capability probe and then refuses: `run` returned 99 and printed not one
  # word, `status` said "nothing started" and `wait` answered a confident 124.
  local lrc=0
  if setsid -f true 2>/dev/null; then
    setsid -f ${RESET[@]+"${RESET[@]}"} bash -c "$body" \
      detach "$PIDF" "$RC" "$@" < /dev/null > "$LOG" 2>&1 || lrc=$?
  elif command -v setsid >/dev/null 2>&1; then
    # Without -f, setsid(2) refuses for a process group leader. A subshell plus
    # `&` guarantees the caller is not one, which is the whole of what -f adds.
    ( setsid ${RESET[@]+"${RESET[@]}"} bash -c "$body" \
        detach "$PIDF" "$RC" "$@" < /dev/null > "$LOG" 2>&1 & ) || lrc=$?
  elif command -v perl >/dev/null 2>&1; then
    # No setsid binary at all (macOS): perl's POSIX::setsid is the same call,
    # under the same rule -- the backgrounded subshell is not a group leader.
    ( perl -MPOSIX -e 'POSIX::setsid() or die "detach: setsid: $!\n"; exec @ARGV or die "detach: exec: $!\n"' \
        ${RESET[@]+"${RESET[@]}"} bash -c "$body" \
        detach "$PIDF" "$RC" "$@" < /dev/null > "$LOG" 2>&1 & ) || lrc=$?
  else
    echo "detach: no setsid and no perl here -- nothing can give the job a" >&2
    echo "        session of its own, so a timeout on the caller would kill it." >&2
    echo "        Refusing rather than start a job that does not survive." >&2
    exit 4
  fi
  # The launcher's own failure used to land in the JOB's log and nowhere else:
  # `run` returned non-zero with an empty terminal, and `wait` then reported a
  # job that had never started as "still running" until its bound ran out. The
  # kit's own assertions could not catch this for as long as they only ever ran
  # where the launcher already works; two were added for exactly this.
  # The body publishes the pid third -- it backgrounds the job and arms the
  # forwarding first, deliberately (see above) -- and nothing between those
  # three steps can block, so after 2s its absence is the launcher failing:
  # say so, out loud, with the reason. A fork slow enough to miss that window
  # would report a job that did start as one that did not; the log named here
  # is then empty rather than an error, which is what tells the two apart.
  local waited=0
  while [ ! -f "$PIDF" ] && [ "$waited" -lt 10 ]; do sleep 0.2; waited=$((waited + 1)); done
  if [ ! -f "$PIDF" ]; then
    echo "detach: '$name' did not start -- $LOG" >&2
    [ "$lrc" -eq 0 ] || echo "        the launcher itself exited $lrc" >&2
    sed -n '1,3p' "$LOG" >&2
    return 5
  fi
  echo "detach: started '$name' -> $LOG"
}

# What the job said, handed back WITH the verdict. `wait` used to print only
# "exited 2", so the very next tool call was a grep of the log for which part
# went red -- measured 2026-09-28, two such extra round trips in one session,
# and each one re-sends the caller's whole context, which costs more than the
# output this kit keeps out of it. A finished log is shown whole when it is
# short, and a job run through logged.sh leaves exactly that: its progress
# lines, the failure tail and its verdict (the red `make ci` that prompted this
# was 57 lines). Three tails' worth is the line, derived rather than a sixth
# knob. A longer log -- a job NOT run through logged.sh -- gets its tail and its
# length. Printed BEFORE the status line, because the last line is the verdict.
_show_log() { # <finished|running>
  [ -s "$LOG" ] || return 0
  local n
  if [ "$1" = running ]; then
    # One line, and the latest one: a poll that repeats the log on every call
    # is the stream this kit exists to replace. \r first -- a progress bar
    # writes one "line" that is the whole run.
    echo "    now: $(tail -c 4096 "$LOG" | tr '\r' '\n' | sed 's/\x1b\[[0-9;]*m//g' | grep -v '^[[:space:]]*$' | tail -n 1)"
    return 0
  fi
  n="$(wc -l < "$LOG" | tr -d ' ')"
  if [ "$n" -le $((3 * JOB_TAIL_LINES)) ]; then
    sed 's/\x1b\[[0-9;]*m//g; s/^/    /' "$LOG"
  else
    echo "    --- last $JOB_TAIL_LINES of $n lines ---"
    tail -n "$JOB_TAIL_LINES" "$LOG" | sed 's/\x1b\[[0-9;]*m//g; s/^/    /'
  fi
}

cmd_wait() {
  _name "${1:-}"; local name="$1" bound="${2:-600}"
  # The name was checked and the bound was not, and both ways it went wrong are
  # worse than a refusal: `abc` reached $(( )) and died as bash's own "abc:
  # unbound variable", naming nothing about the cause, while `-5` put the
  # deadline in the past and returned a confident 124 -- "still running after
  # -5s" -- for a job it never waited for. 124 is one of this file's own codes,
  # so that was this kit reporting a verdict it had not earned.
  [[ "$bound" =~ ^[0-9]+$ ]] || {
    echo "detach: '$bound' is not a number of seconds" >&2; exit 2; }
  # Nothing by this name was ever started. Without this the loop sits out the
  # whole bound and then reports a job that never existed as "still running" --
  # the same shape as a polling loop waiting for something that was never going
  # to appear, which is the failure this file exists to make impossible.
  #
  # The predicate is no `.rc` and no `.pid`, NOT "all three absent". All three
  # was wrong and the comment here used to claim it was the only state that
  # means never started: `run` creates the log by redirection before the body
  # publishes the pid, so a job whose LAUNCHER failed has a log, no pid and no
  # rc for ever -- and that state fell through to the loop and got the worst
  # answer this file has, a confident 124 for a job that never existed.
  # Measured 2026-09-24. It also disagreed with `cmd_status`, which answers 2
  # for the same state because it never looks at the log -- while the last line
  # of this comment used to say the two were the same code deliberately. They
  # are now the same predicate, and the suite asserts they agree.
  if [ ! -f "$RC" ] && [ ! -f "$PIDF" ]; then
    # Nothing at all on disk: nobody ever used this name. Answer at once --
    # a bound spent on a typo is the shape above with extra steps.
    if [ ! -f "$LOG" ]; then
      echo "detach: nothing started as '$name'" >&2; return 2
    fi
    # A log and nothing else is TWO states: a job that is starting, and a job
    # whose launcher failed and never will. cmd_run tells them apart with a 2s
    # grace on the pid file -- nothing between backgrounding the job and
    # publishing the pid can block -- so use the same threshold for the same
    # reason rather than inventing a second one.
    local g=0
    while [ ! -f "$PIDF" ] && [ ! -f "$RC" ] && [ "$g" -lt 10 ]; do
      sleep 0.2; g=$((g + 1))
    done
    if [ ! -f "$PIDF" ] && [ ! -f "$RC" ]; then
      echo "detach: nothing started as '$name' -- the launcher left $LOG" >&2
      sed -n '1,3p' "$LOG" >&2
      return 2
    fi
  fi
  local deadline=$((SECONDS + bound)) started=$SECONDS
  while :; do
    if [ -f "$RC" ]; then
      local rc; rc="$(cat "$RC")"
      _show_log finished
      echo "detach: '$name' exited $rc after $((SECONDS - started))s -- $LOG"; return "$rc"
    fi
    if [ -f "$PIDF" ] && ! _alive && [ ! -f "$RC" ]; then
      _show_log finished >&2
      echo "detach: '$name' died without an exit status (killed?) -- $LOG" >&2; return 125
    fi
    [ "$SECONDS" -lt "$deadline" ] || {
      _show_log running >&2
      echo "detach: '$name' still running after ${bound}s -- $LOG" >&2; return 124; }
    sleep 1
  done
}

cmd_status_all() {
  local p base running=0 died=0
  for p in "$DETACH_DIR"/*.pid; do
    [ -e "$p" ] || continue
    base="$(basename "$p" .pid)"
    [ -f "$DETACH_DIR/$base.rc" ] && continue
    if kill -0 "$(cat "$p")" 2>/dev/null; then
      echo "running  $base (pid $(cat "$p")) -- $DETACH_DIR/$base.log"; running=$((running+1))
    else
      echo "DIED without an exit status  $base -- $DETACH_DIR/$base.log" >&2
      died=$((died+1))
    fi
  done
  # Said out loud: an empty print reads the same as "all clear" whether or not
  # this actually looked.
  [ "$running" -gt 0 ] || [ "$died" -gt 0 ] || echo "nothing running"
  # ...and a job that died without a verdict is not "all clear" either. This
  # printed the DIED line to stderr, "nothing running" to stdout and exited 0:
  # the form you reach for to ask "is anything wrong" answered no where a
  # caller reads and yes where it does not. The named form already returned
  # 125, and the header at the top of this file already promised 125 for
  # `status` -- for both of its forms.
  [ "$died" -eq 0 ] || return 125
}

cmd_status() {
  local rc=0
  # `return 0` here threw away the 125 the aggregate form now has.
  if [ -z "${1:-}" ]; then cmd_status_all || rc=$?; return "$rc"; fi
  _name "$1"
  if   [ -f "$RC" ]; then echo "exited $(cat "$RC")"
  elif _alive;       then echo "running (pid $(cat "$PIDF"))"
  elif [ -f "$PIDF" ]; then echo "died without an exit status"; return 125
  else
    # `wait` answers 2 for this state too, and as of 2026-09-24 by the same
    # predicate (no .rc, no .pid). Two of them are possible: a name nobody ran,
    # and a name whose launcher failed -- and only the second leaves a log,
    # which is then the single place the reason exists. Name it instead of
    # making the reader guess which one this is.
    echo "unknown: nothing started as '$1'"
    [ ! -f "$LOG" ] || echo "  the launcher left $LOG"
    return 2
  fi
}

case "${1:-}" in
  run)    shift; cmd_run "$@" ;;
  wait)   shift; cmd_wait "$@" ;;
  status) shift; cmd_status "$@" ;;
  *)      usage; exit 2 ;;
esac
