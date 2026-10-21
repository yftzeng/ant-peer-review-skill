#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Does detach.sh work on THIS machine? Asked end to end, so it cannot drift
# from the implementation the way a hand-written version check does -- and the
# earlier hand-written one did: `command -v setsid` was structurally blind to
# "setsid is here but has no -f", which is exactly Debian 10.
set -uo pipefail
d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
mkdir -p "$t/scripts"; cp "$d"/*.sh "$t/scripts/"; chmod +x "$t/scripts/"*.sh
cd "$t" || exit 1
# The verdict is the ARTEFACT, and ONLY the artefact. Neither call above is
# chained into the test, because `wait` exits with the JOB's status -- which is
# 7 here, on purpose -- so `run && wait && [ ... ]` can never reach the check.
# (Reviewed once and "fixed" to && ; that broke it. The separation is load-
# bearing, which is why it now says so instead of looking like a stray `;`.)
./scripts/detach.sh run  probe -- bash -c 'exit 7' >/dev/null 2>&1 || true
./scripts/detach.sh wait probe 20                 >/dev/null 2>&1 || true
# shellcheck source=./lib-job-output.sh
. "$t/scripts/lib-job-output.sh"
L="$(ant_logs_dir "$t")/detach"
if [ "$(cat "$L/probe.rc" 2>/dev/null)" = 7 ]; then
  echo "detach.sh OK here"; exit 0
fi
echo "detach.sh WILL NOT WORK HERE:"
sed -n '1,4p' "$L/probe.log" 2>/dev/null
exit 1
