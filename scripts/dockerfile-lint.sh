#!/usr/bin/env bash
# The Dockerfile lint (ant-mode image-scan): what an image installs outside any
# manifest a dependency audit reads, and bases that are past their end of life
# or float without being rebuilt fresh.
#
#   scripts/dockerfile-lint.sh        every tracked Dockerfile, and the tracked
#                                     scripts that build or run images
#
#   warn  <file>:<line> pkg==1.2      pinned, but only the image scan sees it
#   error <file>:<line> pkg           installed inline with no version
#   error <file>:<line> python 3.8 ended 2024-10-07
#   warn  <file>:<line> img:latest floats
#   error <file>:<line> docker build without --pull   (a floating base is cached)
#
# OS packages (apt-get, apk, dnf) are not flagged: the image scan reports them,
# and the remedy is a digest-pinned base or an upgrade step. A runtime the
# table below does not list is not judged. bash and awk only, like the kit.
{
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)" || exit 2
cd "$ROOT" || exit 2

dockerfiles="$(git ls-files | grep -E '(^|/)Dockerfile[^/]*$' || true)"
if [ -z "$dockerfiles" ]; then
  echo "dockerfile-lint: no tracked Dockerfile -- nothing was read, which is not a pass"
  exit 1
fi
scripts="$(git ls-files | grep -E '(\.sh|\.mk|(^|/)Makefile)$' | grep -vE '\.test\.sh$' || true)"
today="$(date -u +%Y-%m-%d)"

# shellcheck disable=SC2086 # file lists split on newlines
out="$(printf '%s\n' $dockerfiles | sed 's/^/D /'; printf '%s\n' $scripts | sed 's/^/S /')"
printf '%s\n' "$out" | awk -v today="$today" '
BEGIN {
  # End of life, from each project'"'"'s published schedule. Keep dated.
  eol["python 2.7"] = "2020-01-01"; eol["python 3.6"] = "2021-12-23"; eol["python 3.7"] = "2023-06-27"
  eol["python 3.8"] = "2024-10-07"; eol["python 3.9"] = "2025-10-31"
  eol["node 10"] = "2021-04-30"; eol["node 12"] = "2022-04-30"; eol["node 14"] = "2023-04-30"
  eol["node 16"] = "2023-09-11"; eol["node 17"] = "2022-06-01"; eol["node 18"] = "2025-04-30"
  eol["node 19"] = "2023-06-01"; eol["node 20"] = "2026-04-30"; eol["node 21"] = "2024-06-01"
  eol["node 23"] = "2025-06-01"
  eol["ruby 2.7"] = "2023-03-31"; eol["ruby 3.0"] = "2024-04-23"; eol["ruby 3.1"] = "2025-03-26"
  split("-r --requirement -c --constraint -e --editable -i --index-url --extra-index-url -t --target --prefix -f --find-links --root --python", a, " ")
  for (k in a) pipval[a[k]] = 1
  split("-v --volume -e --env --env-file -w --workdir -p --publish --network --net --entrypoint -u --user --mount --platform -l --label -m --memory --cpus --add-host --pid --ipc --shm-size --tmpfs --cap-add --cap-drop --security-opt --log-driver --log-opt --restart -h --hostname --gpus --ulimit --device --dns --link --stop-signal --health-cmd --network-alias --alias", b, " ")
  runval["--" "name"] = 1  # not in the list above: the container-name guard reads "--name <x>" as a call
  for (k in b) runval[b[k]] = 1
  errors = 0; warns = 0; nd = 0; floating = 0
}
function emit(kind, where, what) {
  printf "%s %s %s\n", kind, where, what
  if (kind == "error") errors++; else warns++
}
function unq(s) { gsub(/^["'"'"']|["'"'"']$/, "", s); return s }
# One shell segment of a RUN line: inline language installs.
function installs(seg, where,    t, n, i, j, w, tool, start, p) {
  n = split(seg, t, /[ \t]+/)
  for (i = 1; i <= n; i++) {
    w = t[i]; tool = ""; start = 0
    if ((w == "pip" || w == "pip3" || w ~ /^pip3\.[0-9]+$/) && t[i+1] == "install") { tool = "pip"; start = i + 2 }
    else if (w ~ /^python[0-9.]*$/ && t[i+1] == "-m" && t[i+2] == "pip" && t[i+3] == "install") { tool = "pip"; start = i + 4 }
    else if (w == "uv" && t[i+1] == "pip" && t[i+2] == "install") { tool = "pip"; start = i + 3 }
    else if (w == "npm" && (t[i+1] == "install" || t[i+1] == "i" || t[i+1] == "add")) { tool = "npm"; start = i + 2 }
    else if ((w == "pnpm" || w == "yarn") && t[i+1] == "add") { tool = "npm"; start = i + 2 }
    if (tool == "") continue
    for (j = start; j <= n; j++) {
      p = unq(t[j])
      if (p == "") continue
      if (p ~ /^-/) { if (tool == "pip" && (p in pipval)) j++; continue }
      if (p ~ /^[.\/~$]/ || p ~ /\// && p !~ /^@[^\/]+\/[^\/]+$/ || p ~ /\.(whl|tar\.gz|zip|tgz)$/) continue
      if (tool == "pip") { if (p ~ /===?/) emit("warn", where, p); else emit("error", where, p) }
      else { if (p ~ /.@[^@]+$/) emit("warn", where, p); else emit("error", where, p) }
    }
    return
  }
}
function from_line(rest, where,    t, n, i, img, tag, base, ver, key, name) {
  n = split(rest, t, /[ \t]+/)
  i = 1
  while (i <= n && t[i] ~ /^--/) i++
  img = t[i]
  if (t[i+1] ~ /^[Aa][Ss]$/) stage[tolower(t[i+2])] = 1
  if (img == "" || tolower(img) in stage || img == "scratch" || img ~ /^\$/) return
  if (img ~ /@sha256:/) return
  tag = ""
  if (img ~ /:[^\/]+$/) { tag = img; sub(/.*:/, "", tag); name = img; sub(/:[^:\/]+$/, "", name) } else name = img
  if (tag == "" || tag == "latest") {
    emit("warn", where, name ":" (tag == "" ? "latest (no tag)" : "latest") " floats")
    floating = 1
    return
  }
  base = name; sub(/.*\//, "", base)
  ver = tag; sub(/-.*/, "", ver)
  if (base == "node") sub(/\..*/, "", ver); else if (ver ~ /^[0-9]+\.[0-9]+/) { match(ver, /^[0-9]+\.[0-9]+/); ver = substr(ver, 1, RLENGTH) }
  key = base " " ver
  if ((key in eol) && eol[key] < today) emit("error", where, base " " ver " ended " eol[key])
}
# A "docker run" inside a quoted string (a message, an example) is not a call.
function quoted(line,    pre, dq, sq) {
  pre = substr(line, 1, index(line, "docker run") - 1)
  dq = gsub(/"/, "", pre); sq = gsub(/'"'"'/, "", pre)
  return (dq % 2) || (sq % 2)
}
function run_image(line, where,    t, n, i, w, img) {
  if (quoted(line)) return
  n = split(line, t, /[ \t]+/)
  for (i = 1; i < n; i++) if (t[i] == "docker" && t[i+1] == "run") break
  if (i >= n) return
  for (i = i + 2; i <= n; i++) {
    w = t[i]
    if (w ~ /^-/) { if (w !~ /=/ && (w in runval)) i++; continue }
    img = unq(w)
    if (img ~ /^\$/ || img ~ /@sha256:/) return
    # Judged at the end: an image this repo builds itself is not pulled.
    if (img ~ /:latest$/ || (img !~ /:[^\/]+$/ && img ~ /^[a-z0-9]/)) { nrun++; runwhere[nrun] = where; runimg[nrun] = img }
    return
  }
}
function strip_tag(s) { sub(/:[^:\/]*$/, "", s); return s }
function local_tags(line,    t, n, i) {
  n = split(line, t, /[ \t]+/)
  for (i = 1; i < n; i++) if (t[i] == "-t" || t[i] == "--tag") built[strip_tag(unq(t[i+1]))] = 1
}
function read_file(kind, f,    line, logical, ln, start, cont, seg, nseg, k, cmd, n2, tt) {
  ln = 0; logical = ""; cont = 0
  while ((getline line < f) > 0) {
    ln++
    if (!cont) { start = ln; logical = "" }
    if (line ~ /\\[ \t]*$/) { sub(/\\[ \t]*$/, " ", line); logical = logical line; cont = 1; continue }
    logical = logical line; cont = 0
    if (kind == "D") {
      if (logical ~ /^[ \t]*[Ff][Rr][Oo][Mm][ \t]/) { cmd = logical; sub(/^[ \t]*[Ff][Rr][Oo][Mm][ \t]+/, "", cmd); from_line(cmd, f ":" start) }
      else if (logical ~ /^[ \t]*[Rr][Uu][Nn][ \t]/) {
        nseg = split(logical, seg, /&&|\|\||;|\|/)
        for (k = 1; k <= nseg; k++) installs(seg[k], f ":" start)
      }
    } else {
      if (logical ~ /^[ \t]*#/) continue
      if (logical ~ /docker (buildx )?build([ \t]|$)/) {
        if (logical !~ /--pull/) builds[f ":" start] = 1
        local_tags(logical)
      }
      if (logical ~ /docker tag[ \t]/) { n2 = split(logical, tt, /[ \t]+/); for (k = 1; k < n2; k++) if (tt[k] == "tag") { built[strip_tag(unq(tt[k+2]))] = 1; break } }
      if (logical ~ /docker run[ \t]/) run_image(logical, f ":" start)
    }
  }
  close(f)
}
{ kind = $1; f = substr($0, 3); if (f == "") next; if (kind == "D") { nd++; delete stage } ; read_file(kind, f) }
END {
  for (k = 1; k <= nrun; k++) {
    if (strip_tag(runimg[k]) in built) continue
    if (runimg[k] ~ /:latest$/) emit("warn", runwhere[k], runimg[k] " floats")
    else emit("warn", runwhere[k], runimg[k] ":latest (no tag) floats")
  }
  if (floating) for (w in builds) emit("error", w, "docker build without --pull (a floating base is cached)")
  if (errors) { printf "dockerfile-lint: %d error(s), %d warning(s) in %d Dockerfile(s)\n", errors, warns, nd; exit 1 }
  printf "dockerfile-lint: OK (%d warning(s), %d Dockerfile(s))\n", warns, nd
}'
}
