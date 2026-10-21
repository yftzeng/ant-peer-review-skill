# shellcheck shell=bash
# Part of the ant-mode kit -- the last line is the verdict.
# A long job's output, as an artefact instead of a stream.
#
# Sourced, never executed. Named for what it handles -- not `_lib.sh`: a vague
# name is what a junk drawer looks like from outside, and the next person fills
# it accordingly.
#
# Public API:
#   run_logged <log> <ere|""> <cmd...>
#       Run <cmd>. Full stdout+stderr to <log>. The terminal gets the command
#       line, lines matching <ere> as they arrive, and -- only on failure --
#       the last $JOB_TAIL_LINES lines. Returns the COMMAND's exit status,
#       never the wrapper's.
#   follow_matching <log> <ere>
#       The streaming half on its own. Ends when <log>.done appears.
#   ant_logs_dir <repo>
#       The one root every kit sink writes under: logs_dir= in
#       <repo>/.ant/config (first match), default .ant/work/logs, which
#       ignores itself. Absolute, so callers can cd.
#   sweep_stale_logs <dir> <key-ext> [days]
#       Remove finished jobs older than [days]. <key-ext> is the extension
#       whose PRESENCE means finished -- so an unfinished job is never swept.
#       Names must match $JOB_NAME_ERE; that is what makes it safe.
#
# Consumers:  set -Eeuo pipefail
#             . "$(dirname "$0")/lib-job-output.sh"

ant_logs_dir() {
  local d=""
  [ -f "$1/.ant/config" ] && d="$(sed -n 's/^logs_dir=//p' "$1/.ant/config" | head -1)"
  d="${d:-.ant/work/logs}"
  case "$d" in /*) printf '%s\n' "$d" ;; *) printf '%s/%s\n' "$1" "$d" ;; esac
}

JOB_KEEP_DAYS="${JOB_KEEP_DAYS:-7}"
JOB_TAIL_LINES="${JOB_TAIL_LINES:-25}"
JOB_POLL_SECONDS="${JOB_POLL_SECONDS:-3}"

# The one place that says what a job name may contain, and the only reason
# sweep_stale_logs below can find a job's other artefacts with `"$base".*`.
# `.` is excluded deliberately -- with it allowed that glob reaches into a
# DIFFERENT job; see the comment there for what that did and for why the
# obvious narrower glob is worse. Refusing the name at the door is the narrow
# fix: the alternative is for this function to know every artefact extension
# its callers use, and a second copy of that list is a second thing to drift.
# Deliberately not `${JOB_NAME_ERE:-...}`: the sweep's correctness depends on
# it, so it is not a knob.
#
# The directive below is not decoration: this file is SOURCED, and the gate
# also checks it standalone, where the only readers of this name -- detach.sh
# and logged.sh -- are out of sight. The three JOB_* above escape the same
# warning only because they happen to be read in here as well.
# shellcheck disable=SC2034
JOB_NAME_ERE='^[A-Za-z0-9_-]+$'

# Stream the lines a reader wants while the full log fills up.
#
# Polls against a `<log>.done` sentinel rather than `tail -F`, and that is
# load-bearing, not a style choice. A backgrounded `tail -F | grep` inherits
# the caller's stdout, and killing the subshell does NOT reap the `tail`; any
# caller capturing with `$( ... )` then blocks forever, because command
# substitution waits for EVERY process holding the pipe. Writing the sentinel
# and joining with `wait` ends the follower for real.
# Defined with ( ) rather than { }: the body runs in a subshell, so the `set +e`
# below cannot reach the caller. `set` is shell-global, not function-local, and
# this is PUBLIC API -- a foreground call used to leave the caller's errexit off
# for good, in the one kit whose thesis is that a failure must not pass
# silently. Measured 2026-09-24: the caller's next `false` stopped stopping.
# Not `local -`: bash 3.2 rejects it outright (`local: '-': not a valid
# identifier`, measured), and logged.sh + this file claim bash 3.2.
follow_matching() ( # <log> <ere> -- new matching lines, until <log>.done appears
  set +e                       # a display: one missed grep must not end it
  local log="$1" ere="$2" seen=0 total last=0
  while :; do
    [ -f "$log.done" ] && last=1
    if [ -f "$log" ]; then
      total="$(grep -a -c -E "$ere" "$log" || true)"
      if [ "${total:-0}" -gt "$seen" ]; then
        grep -a -E "$ere" "$log" | sed 's/\x1b\[[0-9;]*m//g' \
          | tail -n +"$((seen + 1))" | sed 's/^/    /'
        seen="$total"
      fi
    fi
    [ "$last" = 1 ] && break
    sleep "$JOB_POLL_SECONDS"
  done
)

# The one that matters. Note what is NOT here: no pipe between the command and
# the status. A pipeline's status is the LAST command's, so `cmd | tail` hands
# back tail's success and a red gate reads as green.
run_logged() { # <log> <ere|""> <cmd...> -> the COMMAND's exit status
  local log="$1" ere="$2" rc=0 fpid=""
  shift 2
  mkdir -p "$(dirname "$log")"
  rm -f "$log" "$log.done"
  echo "  $* > ${log#"$PWD"/}"
  if [ -n "$ere" ]; then follow_matching "$log" "$ere" & fpid=$!; fi
  # No errexit around "$@" on purpose: its status is the answer, not a failure
  # of this function.
  "$@" > "$log" 2>&1 || rc=$?
  touch "$log.done"
  [ -n "$fpid" ] && { wait "$fpid" || true; }
  if [ "$rc" -ne 0 ]; then
    echo "  --- last $JOB_TAIL_LINES lines of ${log#"$PWD"/} ---" >&2
    tail -n "$JOB_TAIL_LINES" "$log" | sed 's/\x1b\[[0-9;]*m//g; s/^/    /' >&2
  fi
  return "$rc"
}

# A directory the agent writes to IS an index, so `ls` on an unbounded one
# becomes a large answer to a question nobody asked. Keyed on the extension
# that means FINISHED: a job with no key file is either still running or died
# without saying so, and the second one is the evidence you most want kept.
sweep_stale_logs() {
  local dir="$1" key="$2" days="${3:-$JOB_KEEP_DAYS}" k base
  [ -d "$dir" ] || return 0
  for k in "$dir"/*."$key"; do
    [ -e "$k" ] || continue
    [ -n "$(find "$k" -maxdepth 0 -mtime +"$days" 2>/dev/null)" ] || continue
    base="${k%.$key}"
    # This glob is correct only because a name cannot contain `.` (JOB_NAME_ERE
    # above). With dots allowed it also matched a DIFFERENT job: sweeping a
    # finished `build` deleted a running `build.api`'s .pid and .log, after
    # which `wait build.api` said "nothing started as" about a job `pgrep`
    # could still see -- the one thing this kit must never say.
    # `[ "${f%.*}" = "$base" ] && rm -f "$f"` in a loop looks like the fix and
    # is worse on both counts (measured 2026-09-24): it keeps `<name>.log.done`
    # and `<name>.rc.tmp` for ever -- every logged job leaves a .done, and once
    # the key file is gone nothing ever looks at that base again -- and the
    # failing test is the LAST command of the loop, so the function returns 1
    # and errexit takes the caller down: `logged.sh` exiting 1 with no output
    # at all, seven days after its first job. The suite missed that because its
    # fixture names sort so that the last iteration happens to succeed.
    rm -f "$base".*
  done
}
