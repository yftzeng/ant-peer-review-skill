#!/usr/bin/env bash
# Report whether each GitHub reference pinned in docs/REFERENCES.md changed upstream.
# Read-only: it never edits the file; moving a pin is a reviewed edit by hand.
# Needs git and the network (REFS_GIT_BASE overrides https://github.com, for tests).
# usage: scripts/refs-drift.sh [docs/REFERENCES.md]
# exit: 0 no pinned path changed, 1 a pinned path changed, 2 a repo could not be read
set -uo pipefail

refs=${1:-docs/REFERENCES.md}
base=${REFS_GIT_BASE:-https://github.com}
[ -r "$refs" ] || { echo "refs-drift: FAIL -- cannot read $refs"; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

pins=$(grep -oE 'https://github\.com/[^/ )]+/[^/ )]+/(tree|blob)/[0-9a-f]{40}(/[^ )#]*)?' "$refs" |
  sed -E 's#^https://github\.com/([^/]+)/([^/]+)/(tree|blob)/([0-9a-f]{40})/?(.*)$#\1 \2 \4 \5#' | sort -u)
[ -n "$pins" ] || { echo "refs-drift: FAIL -- no pinned GitHub reference in $refs"; exit 2; }

total=0 changed=0 failed=0
while read -r owner repo pin path; do
  total=$((total + 1))
  path=${path%/}
  label="$owner/$repo ${path:-.}"
  dir="$work/$owner/$repo"
  if [ ! -d "$dir" ] && ! git clone -q --bare --filter=blob:none "$base/$owner/$repo" "$dir" 2>/dev/null; then
    rm -rf "$dir"
    echo "$label UNREADABLE (clone failed)"
    failed=$((failed + 1))
    continue
  fi
  head=$(git -C "$dir" rev-parse HEAD)
  if ! git -C "$dir" cat-file -e "$pin^{commit}" 2>/dev/null; then
    echo "$label CHANGED: pin ${pin:0:12} is no longer upstream (head ${head:0:12})"
    changed=$((changed + 1))
    continue
  fi
  if [ "$head" = "$pin" ]; then
    echo "$label same"
    continue
  fi
  n=$(git -C "$dir" rev-list --count "$pin..$head" -- ${path:+"$path"})
  if [ "$n" -eq 0 ]; then
    echo "$label moved, path unchanged (head ${head:0:12})"
    continue
  fi
  echo "$label CHANGED: $n commit(s) touch it since ${pin:0:12}"
  git -C "$dir" diff --no-renames --name-status "$pin" "$head" -- ${path:+"$path"} | sed 's/^/    /'
  echo "    https://github.com/$owner/$repo/compare/${pin:0:12}...${head:0:12}"
  changed=$((changed + 1))
done <<< "$pins"

if [ "$failed" -gt 0 ]; then
  echo "refs-drift: FAIL -- $failed of $total pinned paths could not be read"
  exit 2
fi
if [ "$changed" -gt 0 ]; then
  echo "refs-drift: CHANGED -- $changed of $total pinned paths changed upstream; review them, then move the pins and 'Upstream last checked' by hand"
  exit 1
fi
echo "refs-drift: PASS -- $total pinned paths, none changed upstream; set 'Upstream last checked' to $(date +%F)"
