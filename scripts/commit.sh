#!/usr/bin/env -S bash -p
# Part of the ant-mode kit -- the last line is the verdict.
# Commit only on a green gate, and only the paths named.
#
#   scripts/commit.sh [git commit args] -- <path>...         gate, then commit
#   scripts/commit.sh --red [git commit args] -- <path>...   failing-test commit:
#                                                no gate, the subject says "(red)"
#   scripts/commit.sh --change <name> [git commit args] -- <path>...
#                                                gate, then commit with the change's
#                                                approval and EVIDENCE as trailers
#   scripts/commit.sh --gate <cmd> ...               <cmd> is the gate this once,
#                                                in place of gate= (shown in the command)
#
# `-F -` reads the message from stdin, as with git.
#
# The gate is --gate <cmd>, else the `gate=` line of .ant/config, else
# scripts/precommit.sh. It is named on the command line or not at all: an
# exported COMMIT_GATE once replaced it on every later commit, unseen, so one
# set in the environment is refused. The kit's files stay identical to the
# template; the repo's choice lives in the repo.
#
# The paths are committed as they are in the working tree (`git commit --only`):
# new, changed and deleted files alike, and nothing else. Whatever else is
# staged -- another session's work, in a shared tree -- stays staged and out
# of the commit.
#
# Why a hook as well: twice a commit ran on a red gate because the two were
# joined by something other than `&&` (`gate | tail -3 && git commit`, then
# `gate ...; git commit`). pre-commit.hook refuses any commit this script did
# not just clear, so the gate is not a step to remember: a bare `git commit`
# stops with instructions. The pass is one-shot and bound to the tree being
# committed (`git write-tree`), one file per tree, so staging something else
# after the gate does not ride on its verdict.
#
# --change <name>: the feature specs (specs/features/, features= in
# .ant/config) are versioned and committed with the change; its approval and
# EVIDENCE live in .ant/work/<name>/ (ignored) and leave as trailers, read here
# from the files `ant change` and `ant evidence` wrote, so the kit needs no
# plugin:
#   Change: <name>
#   Spec-approval: auto | human "<words>" (specs <hash>, gauntlet <hash>)
#   Spec-scenarios: +S-.. ~S-.. -S-..        added, changed, removed
#   Evidence: PASS tier <n>, <x> run <y> not run
#   Evidence-not-run: <layer> -- <n-a|unavailable|substituted> -- <reason>
#   Evidence-review: <models>               a tier 3-4 review, reviewers and author
#   Evidence-review-usage: <usage>          each reviewer's usage (ant review usage)
#   Evidence-security: <tools> (classes: ..) the security lens of a tier 3-4 review
#   Evidence-tier-override: <why>           a --tier below the changed files' floor
#   Decision: D-<n> | none -- <reason>       from the change's Revisions lines
# Refused, nothing committed: no approval, or a feature spec or
# .ant/gauntlet.conf changed since it; no PASS EVIDENCE; a named path that
# differs from the tree the EVIDENCE ran on (paths not named -- another
# session's edits in a shared tree -- do not count); a feature changed since
# the base that is not among the paths; a changed feature with no new
# Revisions line, or one that names no decision; a removed scenario not
# recorded as -<id>; a named D-<n> whose record is not in the commit; with
# evidence=commit, the report not among the paths; --red.
#
# A green gate also writes <logs_dir>/ant/last-gate (time + tree): `ant push-scope`
# reads it to flag commits the gate never saw. A --gate commit writes none.
#
# The body is one brace group ending in exit, so bash reads it whole before it
# runs: a gate takes minutes, and an edit made meanwhile must not be read at the
# old byte offset.
#
# The first line starts `bash -p`: the caller's bash imports no exported
# function and reads no BASH_ENV, SHELLOPTS or BASHOPTS, all of which ran
# before line 1 and could commit on a red gate (`export -f env`). Run as
# `bash scripts/commit.sh` it starts itself again that way, best effort only:
# that outer bash has already read BASH_ENV and the caller's functions (one
# named exec defeats the restart), so run it directly. git's location and
# config variables (GIT_DIR, GIT_CONFIG_GLOBAL, ...) would swap the
# repository, index or config being checked, and the loader's (LD_PRELOAD,
# ...) the code doing the checking, so one that is set is refused.
{
[[ -o privileged ]] || exec bash -p -- "$0" "$@"
set -euo pipefail

for v in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_EXEC_PATH LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH; do
  if [[ -n "${!v+set}" ]]; then
    echo "commit.sh: $v is set -- it would change which repository, config or code is checked; unset it" >&2
    exit 1
  fi
done
# A replace ref could show the checks a clean tree in place of the one
# committed; gate_env_run sets it again for the gate and the scanner.
export GIT_NO_REPLACE_OBJECTS=1

if [[ -n "${COMMIT_GATE+set}" ]]; then
  echo "commit.sh: COMMIT_GATE is not read -- name the gate with --gate" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
GITDIR="$(git rev-parse --git-dir)"
conf_gate=""
if [[ -f "$ROOT/.ant/config" ]]; then
  conf_gate="$(sed -n 's/^gate=//p' "$ROOT/.ant/config" | head -1)"
fi
# The kit's one sink root: logs_dir= in .ant/config, default .ant/work/logs.
LOGS=""
[[ -f "$ROOT/.ant/config" ]] && LOGS="$(sed -n 's/^logs_dir=//p' "$ROOT/.ant/config" | head -1)"
LOGS="${LOGS:-.ant/work/logs}"; [[ "$LOGS" == /* ]] || LOGS="$ROOT/$LOGS"

red=0
change="" covered="" etree="" gate_arg="" floor_because="" fb_set=0 change_fl=""
args=()
paths=()
tmp=""
while (( $# )); do
  case "$1" in
    --) shift; paths=("$@"); break ;;
    --red) red=1; shift ;;
    --gate) gate_arg="${2:?--gate needs a command}"; shift 2 ;;
    --change) change="${2:?--change needs a change name}"; shift 2 ;;
    --floor-because) floor_because="${2?--floor-because needs a reason}"; fb_set=1; shift 2 ;;
    -F)
      if [[ "${2:-}" == "-" ]]; then
        tmp="$(mktemp)"; cat > "$tmp"; args+=(-F "$tmp")
      else
        args+=(-F "${2:?-F needs a file}")
      fi
      shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
GATE="${gate_arg:-${conf_gate:-scripts/precommit.sh}}"
# The keys that choose what the gate runs are read from the working copy, so
# an uncommitted gate=true would decide every later commit, unseen in the
# command (S-commit-011). Once HEAD has an .ant/config they must match it:
# gate= and gate_covered_by= unless --gate names the gate; gate_env=,
# secret_scan= and secret_scan_found_rc= unless .ant/config is one of the
# named paths, so the commit carries the change that decides it.
if git cat-file -e HEAD:.ant/config 2>/dev/null; then
  hconf="$(git show HEAD:.ant/config)"
  wconf="$(cat "$ROOT/.ant/config" 2>/dev/null || true)"
  conf_named=0
  grep -qxF .ant/config <<<"$(git ls-files --full-name -- "${paths[@]}" 2>/dev/null)" && conf_named=1
  for k in gate gate_covered_by gate_env secret_scan secret_scan_found_rc; do
    wv="$(sed -n "s/^$k=//p" <<<"$wconf" | head -1)"
    hv="$(sed -n "s/^$k=//p" <<<"$hconf" | head -1)"
    [[ "$wv" == "$hv" ]] && continue
    case "$k" in
      gate|gate_covered_by) [[ -n "$gate_arg" ]] && continue; how="commit it with --gate <cmd> naming the gate" ;;
      *) (( conf_named )) && continue; how="commit it with .ant/config among the named paths" ;;
    esac
    echo "commit.sh: .ant/config has an uncommitted $k= ('$wv', HEAD '$hv') -- it would decide this commit unseen; restore it, or $how" >&2
    exit 1
  done
fi

subject(){
  local i
  for (( i = 0; i < ${#args[@]}; i++ )); do
    case "${args[$i]}" in
      -m) printf '%s\n' "${args[$((i + 1))]:-}" | head -1; return ;;
      -F) head -1 "${args[$((i + 1))]}"; return ;;
    esac
  done
}

if (( ${#paths[@]} == 0 )); then
  echo "commit.sh: name what to commit: scripts/commit.sh [args] -- <path>..." >&2
  echo "  (staged files that are not yours stay out)" >&2
  exit 1
fi
# Known to git first, so an untracked new file can be named. A deleted path is
# already known (it is in HEAD) and would make `git add` fail, so skip it.
# ${a[@]+"${a[@]}"}: bash before 4.4 calls an empty array unbound under -u.
present=()
for p in "${paths[@]}"; do [[ -e "$p" ]] && present+=("$p"); done
(( ${#present[@]} )) && git add -A -- "${present[@]}"
# The tree this commit will have: HEAD plus the named paths as they are now.
# git commit --only builds the same index for the hook, so the pass below is
# bound to it and to nothing that is merely staged.
idx="$(mktemp)"
MARK=""
msgf=""
trap '[[ -n "$tmp" ]] && rm -f "$tmp"; [[ -n "$msgf" ]] && rm -f "$msgf"; rm -f "$idx"; [[ -n "$MARK" ]] && rm -f "$MARK"' EXIT
tree_now(){
  if git rev-parse -q --verify HEAD >/dev/null; then
    GIT_INDEX_FILE="$idx" git read-tree HEAD
  else
    GIT_INDEX_FILE="$idx" git read-tree --empty
  fi
  GIT_INDEX_FILE="$idx" git add -A -- "${paths[@]}"
  GIT_INDEX_FILE="$idx" git write-tree
}
tree="$(tree_now)"
if [[ "$tree" == "$(git rev-parse -q --verify 'HEAD^{tree}' || true)" ]]; then
  echo "commit.sh: nothing to commit in: ${paths[*]}" >&2
  exit 1
fi
others="$(git diff --cached --name-only -- . | grep -vxF -f <(git diff --cached --name-only -- "${paths[@]}") || true)"
if [[ -n "$others" ]]; then
  echo "commit.sh: staged but not named, left staged and out of this commit:" >&2
  sed 's/^/  /' <<<"$others" >&2
fi

ch_fail(){ echo "commit.sh --change: $*" >&2; exit 1; }
# The message: every -m paragraph and -F file, then the trailers in their own
# last paragraph (`git commit --trailer` needs git 2.32).
add_trailers(){  # <trailer lines>
  local i=0; local -a rest=()
  msgf="$(mktemp)"
  while (( i < ${#args[@]} )); do
    case "${args[$i]}" in
      -m) printf '%s\n\n' "${args[$((i + 1))]:-}" >> "$msgf"; i=$((i + 2)) ;;
      -F) cat "${args[$((i + 1))]}" >> "$msgf"; i=$((i + 2)) ;;
      *) rest+=("${args[$i]}"); i=$((i + 1)) ;;
    esac
  done
  [[ -s "$msgf" ]] || { echo "commit.sh: a trailer needs the message as -m or -F" >&2; exit 1; }
  awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] ~ /^[[:space:]]*$/) n--; for (i = 1; i <= n; i++) print l[i] }' "$msgf" > "$msgf.body"
  grep -q '[^[:space:]]' "$msgf.body" || { echo "commit.sh: the message is empty; a trailer is not a message" >&2; exit 1; }
  { cat "$msgf.body"; printf '\n%s\n' "$1"; } > "$msgf"
  rm -f "$msgf.body"
  args=(${rest[@]+"${rest[@]}"} -F "$msgf")
}
# The tier floor of the files this commit carries (S-commit-006). The same
# rule as `ant evidence` (S-evidence-011) -- the kit calls nothing from the
# plugin, so it is written here again: path and content keys from the working
# and HEAD's .ant/config; content keys only for files in content_scope, read
# from the working copy and HEAD's (removing a guard keeps the floor); paths
# unquoted and NUL-separated; a key that does not compile refuses.
# Prints "<floor>\t<key>\t<file>", nothing for no floor.
commit_files(){  # the files the named paths contribute, NUL-separated
  { git -c core.quotePath=false diff -z --name-only --no-renames HEAD -- "${paths[@]}" 2>/dev/null
    git -c core.quotePath=false ls-files -z --others --exclude-standard -- "${paths[@]}"; } | sort -zu
}
# Whether a file's content matches: the working copy or HEAD's (the commit
# being made: removing a guard keeps the floor), or -- for a past commit --
# the revisions given (that commit and its parents). Arguments, never an
# inherited variable: nothing outside can switch the content floor off.
floor_holds() {  # <ere> <file> [rev...]
  local r e="$1" f="$2"
  shift 2
  if [ "$#" -gt 0 ]; then
    for r in "$@"; do
      git -C "$ROOT" cat-file -e "$r:$f" 2>/dev/null &&
        grep -qE -- "$e" <<<"$(git -C "$ROOT" show "$r:$f" 2>/dev/null)" && return 0
    done
    return 1
  fi
  { [ -f "$ROOT/$f" ] && grep -qE -- "$e" "$ROOT/$f" 2>/dev/null; } ||
    { git -C "$ROOT" cat-file -e "HEAD:$f" 2>/dev/null &&
      grep -qE -- "$e" <<<"$(git -C "$ROOT" show "HEAD:$f" 2>/dev/null)"; }
}
# floor_under <config text>: the floor of the files in _ff (NUL-free paths)
# under that one config, whole: its own keys and its own content_scope (unset
# = every file). Prints "<floor>\t<key>\t<file>", nothing for no floor; an ERE
# that does not compile prints "! <key>" and returns 2.
floor_under() {  # <config text> [rev...]
  local cfg="$1" k ere t f sc rc
  shift
  local -a inscope=()
  for k in tier4_paths tier4_content tier3_paths tier3_content content_scope; do
    ere="$(sed -n "s/^$k=//p" <<<"$cfg" | head -1 | sed 's/[[:space:]]*$//')"
    [ -n "$ere" ] || continue
    rc=0; grep -qE -- "$ere" </dev/null 2>/dev/null || rc=$?
    [ "$rc" -lt 2 ] || { echo "! $k"; return 2; }
  done
  [ "${#_ff[@]}" -gt 0 ] || return 0
  sc="$(sed -n 's/^content_scope=//p' <<<"$cfg" | head -1 | sed 's/[[:space:]]*$//')"
  if [ -n "$sc" ]; then
    while IFS= read -r -d '' f; do inscope+=("$f"); done < <(printf '%s\0' "${_ff[@]}" | grep -zE -- "$sc")
  else inscope=("${_ff[@]}"); fi
  for t in 4 3; do
    ere="$(sed -n "s/^tier${t}_paths=//p" <<<"$cfg" | head -1 | sed 's/[[:space:]]*$//')"
    if [ -n "$ere" ]; then
      f="$(printf '%s\0' "${_ff[@]}" | grep -zE -m 1 -- "$ere" | tr -d '\0')"
      [ -z "$f" ] || { printf '%s\t%s\t%s\n' "$t" "tier${t}_paths" "$f"; return 0; }
    fi
    ere="$(sed -n "s/^tier${t}_content=//p" <<<"$cfg" | head -1 | sed 's/[[:space:]]*$//')"
    [ -n "$ere" ] || continue
    for f in ${inscope[@]+"${inscope[@]}"}; do
      if floor_holds "$ere" "$f" "$@"; then
        printf '%s\t%s\t%s\n' "$t" "tier${t}_content" "$f"; return 0
      fi
    done
  done
}
# The floor of the files named on stdin (NUL-separated): computed under the
# working .ant/config and under HEAD's, each whole, the higher one counts --
# editing the file cannot lift the committed policy, and narrowing a scope
# waits for the commit that does it.
# shellcheck disable=SC2120  # scripts/commit.sh passes no revisions; lib.sh's commit_floor does
tier_floor() {  # [rev...] -- files on stdin; revs: read content from those, not the tree
  local w h rw=0 rh=0 fw=0 fh=0 f
  _ff=()
  while IFS= read -r -d '' f; do _ff+=("$f"); done
  w="$(floor_under "$(cat "$ROOT/.ant/config" 2>/dev/null)" "$@")" || rw=$?
  h="$(floor_under "$(git -C "$ROOT" show HEAD:.ant/config 2>/dev/null)" "$@")" || rh=$?
  [ "$rw" -lt 2 ] || { echo "$w"; return 2; }
  [ "$rh" -lt 2 ] || { echo "$h"; return 2; }
  [ -z "$w" ] || fw="${w%%$'\t'*}"
  [ -z "$h" ] || fh="${h%%$'\t'*}"
  if [ "$fh" -gt "$fw" ]; then echo "$h"; elif [ -n "$w" ]; then echo "$w"; fi
}
ch_floor(){  # the commit's floor; exits the script (not just the $(...)) on a bad key
  local out rc=0
  out="$(commit_files | tier_floor)" || rc=$?
  if (( rc >= 2 )); then echo "commit.sh: ${out#! } in .ant/config does not compile -- a floor that matches nothing is no floor" >&2; return 2; fi
  [[ -z "$out" ]] || echo "$out"
}
cconf(){ [[ -f "$ROOT/.ant/config" ]] || return 0; sed -n "s/^$1=//p" "$ROOT/.ant/config" | head -1; }
# The environment a gate or an evidence layer runs in: an allow-list, never
# the caller's whole environment -- MAKEFLAGS=i / GNUMAKEFLAGS=i made a failing
# make gate pass, a `?=` make variable (or a command-line variable smuggled in
# GNUMAKEFLAGS) could empty a recipe, BASH_ENV runs code first (retroactive
# security review, 2026-10-27). gate_env= in .ant/config names more to keep.
# PATH stays: it is how the gate finds its tools.
gate_env_run() {  # <command...>
  local v a=() keep
  keep="PATH HOME USER LOGNAME LANG LC_ALL TERM TMPDIR $(cconf gate_env)"
  for v in $keep; do
    case "$v" in *[!A-Za-z0-9_]*|MAKEFLAGS|GNUMAKEFLAGS|MFLAGS|MAKEFILES|MAKELEVEL|BASH_ENV|ENV) continue ;; esac
    [ -z "${!v+x}" ] || a+=("$v=${!v}")
  done
  env -i "${a[@]}" GIT_NO_REPLACE_OBJECTS=1 "$@"
}
revisions(){ awk '/^## / { r = ($0 ~ /^## Revisions/); next } r && /^- / { print }'; }
# A here-string, not `git show | grep -q`: a spec over the pipe buffer would
# SIGPIPE git when grep stops early, and read as "not a feature".
was_feature(){ grep -q '^```gherkin' <<<"$(git -C "$ROOT" show "$2:$1" 2>/dev/null || true)"; }
is_feature(){ [[ -f "$ROOT/$1" ]] && grep -q '^```gherkin' "$ROOT/$1"; }
ch_changed_features(){  # <base> -- the same rule as the plugin's changed_features
  local d f bdirs
  # The directories features= names now and named at <base>.
  bdirs="$({ git -C "$ROOT" show "$1:.ant/config" 2>/dev/null || true; } | sed -n 's/^features=//p' | head -1)"
  for d in $(printf '%s\n' $fdirs ${bdirs:-specs/features} | sort -u); do
    git -C "$ROOT" diff --name-only "$1" -- "$d"
    if [[ -d "$ROOT/$d" ]]; then git -C "$ROOT" ls-files --others --exclude-standard -- "$d"; fi
  done | sort -u | while IFS= read -r f; do
    [[ "$f" == *.md ]] || continue
    if is_feature "$f" || was_feature "$f" "$1"; then echo "$f"; fi
  done
}
ch_state(){  # <base> -- what an approval is bound to
  local f
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    if [[ -f "$ROOT/$f" ]]; then echo "feature $f $(git hash-object "$ROOT/$f")"; else echo "feature $f deleted"; fi
  done < <(ch_changed_features "$1")
  if [[ -f "$ROOT/.ant/gauntlet.conf" ]]; then echo "gauntlet $(git hash-object "$ROOT/.ant/gauntlet.conf")"; else echo "gauntlet none"; fi
}
# In the commit as it is in the working tree (or absent from both)?
in_commit(){  # <tree> <path>
  local t w=""
  t="$(git rev-parse -q --verify "$1:$2" || true)"
  [[ -f "$ROOT/$2" ]] && w="$(git hash-object "$ROOT/$2")"
  [[ "$t" == "$w" ]]
}
# The EVIDENCE ran on a tree: the named paths must be as they were then; the
# change's features, its report and its decisions must be in the commit.
# Checked before the gate and again on the tree that is actually committed.
ch_fresh(){  # <tree>
  local changed listing f d
  changed="$(git diff --name-only "$etree" "$1" -- "${paths[@]}")"
  [[ -z "$changed" ]] || ch_fail "$change: the EVIDENCE is stale for: $(tr '\n' ' ' <<<"$changed")-- rerun: ant evidence $change --tier N"
  for f in $feats; do in_commit "$1" "$f" || ch_fail "$f changed in this change and is not among the paths -- commit the spec with it"; done
  [[ -z "$report" ]] || in_commit "$1" "$report" || ch_fail "evidence=commit: the report $report is not among the paths"
  # A here-string, not `ls-tree | grep -q`: under pipefail an early-exiting
  # grep can SIGPIPE the writer and turn a match into a failure.
  listing="$(git ls-tree -r --name-only "$1" -- "$ddir/")"
  for d in $dec_ids; do
    grep -qE "^$ddir/$d(-.*)?\.md$" <<<"$listing" ||
      ch_fail "a Revisions line names $d, and no $ddir/$d-*.md is in this commit -- name it with the paths"
  done
}
# S-commit-008: --red --change <name> names the change the failing test is
# for -- "Change: <name>" and nothing else of it (no evidence exists yet), so
# push-scope can credit the commit to the change's evidence commit.
red_change=""
if [[ -n "$change" ]] && (( red )); then
  [[ "$change" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "commit.sh: '$change' is not a change name" >&2; exit 1; }
  [[ -f "$ROOT/.ant/work/$change/base" ]] || { echo "commit.sh: no change $change -- ant change new $change" >&2; exit 1; }
  red_change="$change" change=""
fi
if [[ -n "$change" ]]; then
  [[ "$change" =~ ^[a-z0-9][a-z0-9-]*$ ]] || ch_fail "'$change' is not a change name"
  W="$ROOT/.ant/work/$change"
  [[ -f "$W/base" ]] || ch_fail "no change $change -- ant change new $change"
  base="$(cat "$W/base")"
  fdirs="$(cconf features)"; fdirs="${fdirs:-specs/features}"
  ddir="$(cconf decisions)"; ddir="${ddir:-specs/decisions}"
  [[ -f "$W/approval" ]] || ch_fail "$change is not approved -- ant change approve $change"
  # A set, not a sequence: compared sorted.
  was="$(grep -E '^(feature|gauntlet) ' "$W/approval" | sort || true)"
  [[ -n "$was" && "$was" == "$(ch_state "$base" | sort)" ]] ||
    ch_fail "$change drifted since approval (a feature spec or .ant/gauntlet.conf) -- show the change and approve again"
  a_mode="$(sed -n 's/^mode //p' "$W/approval")" a_by="$(sed -n 's/^by //p' "$W/approval")"
  a_specs="$(grep '^feature ' "$W/approval" | git hash-object --stdin || true)"
  a_gauntlet="$(sed -n 's/^gauntlet //p' "$W/approval")"
  E="$W/EVIDENCE.md" verdict=""
  # The verdict is the report's last line, and layer rows come from its layer
  # table: notes and a model review are pasted into the report, and a line in
  # them that quotes a verdict or a row must not speak for it. The header
  # fields below are written before anything pasted, so their first match is
  # theirs.
  layers=""
  if [[ -f "$E" ]]; then
    verdict="$(tail -n 1 "$E" | sed -n 's/^verdict: //p')"
    # The first table only: ant evidence writes it before anything pasted, and
    # a table quoted in the notes must not stand in for it (S-commit-005).
    layers="$(awk '/^\| layer \| tier \|/ { on = 1 } on && /^$/ { exit } on' "$E")"
  fi
  [[ "$verdict" == "PASS ("*")" ]] || ch_fail "$change has no passing EVIDENCE -- ant evidence $change --tier N"
  etree="$(sed -n 's/^- source tree \([0-9a-f]\{40\}\).*/\1/p' "$E" | head -1)"
  { [[ -n "$etree" ]] && git cat-file -e "$etree^{tree}" 2>/dev/null; } ||
    ch_fail "$change: its EVIDENCE names no source tree this repo has -- rerun ant evidence"
  etier="$(sed -n 's/^- run: .*, tier \([1234]\),.*/\1/p' "$E" | head -1)"
  hdr="$(sed -n '1,/^## /p' "$E")"
  # An override counts for the floor it was granted against, not a higher one.
  o_floor="$(sed -n 's/^- tier override: [1234] below floor \([1234]\) .*/\1/p' <<<"$hdr" | head -1)"
  # ...and only when the file it names is one this commit carries: compared
  # with the committed files, not parsed out of the reason.
  o_hit=0
  while IFS= read -r -d '' f; do
    [[ "$hdr" == *"- tier override: "[1234]" below floor "[1234]" ($f): "* ]] && o_hit=1
  done < <(commit_files)
  change_floor(){  # refuses when the commit's floor is above the EVIDENCE's tier and its override
    local fl f_tier f_file
    fl="$(ch_floor)" || exit 1
    [[ -n "$fl" ]] || { change_fl=""; return 0; }
    IFS=$'\t' read -r f_tier _ f_file <<<"$fl"
    if (( ${etier:-0} < f_tier )) && ! { (( o_hit )) && (( ${o_floor:-0} >= f_tier )); }; then
      ch_fail "$change: EVIDENCE tier ${etier:-?} is below the floor $f_tier set by $f_file -- rerun ant evidence $change --tier $f_tier (or --because \"<why>\")"
    fi
    change_fl="$fl"
  }
  change_floor
  scen="$(sed -n 's/^- scenarios: //p' "$E" | head -1)"
  report="$(sed -n 's/^- report: //p' "$E" | head -1)"
  feats="$(ch_changed_features "$base")"
  # Each changed feature gains Revisions lines (append-only, `ant spec lint`),
  # and each names its decision.
  newrev=""
  for f in $feats; do
    [[ -f "$ROOT/$f" ]] || continue
    old="$({ git -C "$ROOT" show "$base:$f" 2>/dev/null || true; } | revisions)"
    n_old="$(grep -c '^' <<<"$old" || true)"; [[ -n "$old" ]] || n_old=0
    added="$(revisions < "$ROOT/$f" | tail -n +"$((n_old + 1))")"
    [[ -n "$added" ]] || ch_fail "no new Revisions line in $f -- add: - <date> · +S-.. ~S-.. -S-.. · D-<n> | decision: none -- <reason>"
    while IFS= read -r line; do
      grep -qE 'D-[0-9]+|decision: none -- [^[:space:]]' <<<"$line" ||
        ch_fail "a Revisions line in $f must name D-<n> or 'decision: none -- <reason>': $line"
    done <<<"$added"
    newrev="${newrev:+$newrev
}$added"
  done
  for id in $scen; do
    case "$id" in -*) ;; *) continue ;; esac
    id="${id#-}"
    grep -qE -- "(^|[[:space:]])-$id([^0-9]|$)" <<<"$newrev" ||
      ch_fail "$id was removed; record it as -$id in a new Revisions line"
  done
  dec_ids="$(grep -oE 'D-[0-9]+' <<<"$newrev" | sort -u || true)"
  nones="$(grep -oE 'decision: none -- .*' <<<"$newrev" | sed 's/^decision: //; s/[[:space:]]*$//' | sort -u || true)"
  counts="${verdict#PASS (}"; counts="${counts%)}"; counts="${counts/, / }"
  trailers="Change: $change
Spec-approval: ${a_mode:-auto}$(if [[ "$a_mode" == human ]]; then printf ' "%s"' "$a_by"; fi) (specs ${a_specs:0:12}, gauntlet ${a_gauntlet:0:12})"
  [[ -z "$scen" || "$scen" == none ]] || trailers="$trailers
Spec-scenarios: $scen"
  trailers="$trailers
Evidence: PASS tier ${etier:-?}, $counts"
  notrun="$(sed -nE 's/^\| ([^|]+) \| [1234] \| [^|]+ \| (n-a|unavailable|substituted): (.*) \| +\| +\| +\|$/Evidence-not-run: \1 -- \2 -- \3/p' <<<"$layers")"
  [[ -z "$notrun" ]] || trailers="$trailers
$notrun"
  # S-evidence-016/017: a review under its round minimum, and a fix no reviewer saw,
  # leave with the commit (EVIDENCE.md stays in .ant/work).
  rounds="$(sed -nE 's/^\| rounds \| [34] \| review\.md \| under the minimum \(([0-9]+ < [0-9]+)\): ([^|]*[^| ]) +\|.*/Evidence-rounds: \1 -- \2/p' <<<"$layers")"
  [[ -z "$rounds" ]] || trailers="$trailers
$rounds"
  unverified="$(sed -nE 's/^\| unverified fixes \| [34] \| review\.md \| unverified: ([^|]*[^| ]) +\|.*/Evidence-unverified: \1/p' <<<"$layers")"
  [[ -z "$unverified" ]] || trailers="$trailers
$unverified"
  review="$(sed -nE 's/^\| review \| [34] \| review\.md \| reviewed: ([^|]*[^| ]) +\|.*/Evidence-review: \1/p' <<<"$layers")"
  [[ -z "$review" ]] || trailers="$trailers
$review"
  security="$(sed -nE 's/^\| security \| [34] \| review\.md \| checked: ([^|]*[^| ]) +\|.*/Evidence-security: \1/p' <<<"$layers")"
  [[ -z "$security" ]] || trailers="$trailers
$security"
  # Header only (before the first section): notes are pasted into the report
  # and must not be able to speak for it.
  usage="$(sed -n '1,/^## /p' "$E" | sed -n 's/^- review usage: \(.*\)/Evidence-review-usage: \1/p' | head -1)"
  [[ -z "$usage" ]] || trailers="$trailers
$usage"
  override="$(sed -n 's/^- tier override: \(.*\)/Evidence-tier-override: \1/p' <<<"$hdr" | head -1)"
  # The override names the file that set the floor; it leaves only when that
  # file is in this commit -- in a shared tree it may be another session's.
  if [[ -n "$override" ]]; then
    if (( o_hit )); then trailers="$trailers
$override"
    else echo "commit.sh: the EVIDENCE's tier override names a file this commit does not carry -- the trailer stays out" >&2; fi
  fi
  for d in $dec_ids; do trailers="$trailers
Decision: $d"; done
  while IFS= read -r n; do [[ -z "$n" ]] || trailers="$trailers
Decision: $n"; done <<<"$nones"
  ch_fresh "$tree"
  # The gate's checks already ran on this tree (S-commit-005): gate_covered_by
  # names the EVIDENCE layer that runs everything the gate runs (make ci runs
  # make precommit's checks), and the tree to commit is the tree it ran on.
  # Any other tree -- another session's commit, a path left out -- runs the gate.
  # Several layers may share the cover (ci + docs); every one must have passed.
  # The layers cover the repo's gate; a gate named by --gate is another
  # command, so it runs.
  cov="$(cconf gate_covered_by)"
  if [[ -n "$cov" && -z "$gate_arg" && "$tree" == "$etree" ]]; then
    covered="$cov"
    for l in $cov; do
      awk -F'|' -v n="$l" '{ for (i = 2; i <= 5; i++) gsub(/^[ \t]+|[ \t]+$/, "", $i) }
        $2 == n && $5 == "pass" { f = 1 } END { exit !f }' <<<"$layers" || covered=""
    done
  fi
  add_trailers "$trailers"
fi

# Without --change (plain or --red), a file with a tier floor of 3 or more is
# not committed on the gate alone (S-commit-006): ant evidence reads only
# uncommitted work, so such a commit would carry it past every floor.
# --floor-because names why and leaves a trailer; the floor is checked again
# on the tree actually committed. A --red commit carries tests (tests= of the
# working or HEAD's .ant/config, else the plugin's default), feature specs,
# the spec index and decision records -- what a failing-test commit holds.
plain_floor(){  # exits on a floored file without --floor-because
  local fl f_tier f_key f_file
  fl="$(ch_floor)" || exit 1
  [[ -n "$fl" ]] || { floor_line=""; return 0; }
  IFS=$'\t' read -r f_tier f_key f_file <<<"$fl"
  if (( ! fb_set )); then
    if (( red )); then
      echo "commit.sh --red: $f_file has a tier floor of $f_tier ($f_key) -- a red commit carries it only with --floor-because \"<why>\"" >&2
    else
      echo "commit.sh: $f_file has a tier floor of $f_tier ($f_key) -- this commit needs --change <name> (ant evidence at tier $f_tier), or --floor-because \"<why>\"" >&2
    fi
    exit 1
  fi
  floor_line="Floor-override: $f_tier ($f_file): $floor_because"
}
floor_line=""
# Only a repo that sets a floor gets these checks; elsewhere commit.sh without
# --change behaves as before (N-commit-001).
floors_on=0 cfg_w="" cfg_h=""
cfg_w="$(cat "$ROOT/.ant/config" 2>/dev/null || true)"
cfg_h="$(git show HEAD:.ant/config 2>/dev/null || true)"
for c in "$cfg_w" "$cfg_h"; do
  grep -qE '^tier[34]_(paths|content)=[^[:space:]]' <<<"$c" && floors_on=1
done
if [[ -z "$change" ]] && (( floors_on )); then
  if (( fb_set )); then
    case "$floor_because" in *$'\n'*|*$'\r'*) echo "commit.sh: --floor-because takes one line" >&2; exit 1 ;; esac
    [[ -n "${floor_because//[[:space:]]/}" ]] || { echo "commit.sh: --floor-because needs a reason" >&2; exit 1; }
  fi
  if (( red )); then
    # What a red commit may carry, under each config: red_paths= (else tests=,
    # else the plugin's default), the feature dirs, the decisions, the index.
    red_allow(){  # <config text> -> one ERE
      local c="$1" v d a
      v="$(sed -n 's/^red_paths=//p' <<<"$c" | head -1)"
      [[ -n "$v" ]] || v="$(sed -n 's/^tests=//p' <<<"$c" | head -1)"
      a="${v:-[Tt][Ee][Ss][Tt]|[Ss][Pp][Ee][Cc]}"
      v="$(sed -n 's/^features=//p' <<<"$c" | head -1)"; for d in ${v:-specs/features}; do a="$a|^${d%/}/"; done
      v="$(sed -n 's/^decisions=//p' <<<"$c" | head -1)"; for d in ${v:-specs/decisions}; do a="$a|^${d%/}/"; done
      v="$(sed -n 's/^index=//p' <<<"$c" | head -1)"; a="$a|^${v:-specs/README.md}\$"
      printf '%s' "$a"
    }
    aw="$(red_allow "$cfg_w")" ah=""
    [[ -z "$cfg_h" ]] || ah="$(red_allow "$cfg_h")"
    for ra in "$aw" "$ah"; do
      [[ -n "$ra" ]] || continue
      rrc=0; grep -qE -- "$ra" </dev/null 2>/dev/null || rrc=$?
      (( rrc < 2 )) || { echo "commit.sh --red: red_paths (or tests=, features=, decisions=, index=) in .ant/config does not compile" >&2; exit 1; }
    done
    nontest=""
    while IFS= read -r -d '' f; do
      printf '%s\0' "$f" | grep -zqE -- "$aw" || { nontest="$nontest $f"; continue; }
      [[ -z "$ah" ]] || printf '%s\0' "$f" | grep -zqE -- "$ah" || nontest="$nontest $f"
    done < <(commit_files)
    [[ -z "$nontest" ]] || { echo "commit.sh --red: the failing-test commit carries tests, feature specs, the spec index and decisions only (red_paths= in .ant/config, else tests=; working and HEAD's); not one of them:$nontest" >&2; exit 1; }
  fi
  plain_floor
  # One call: a second add_trailers starts a new paragraph, which git's trailer
  # parser does not read as trailers.
  rt="$floor_line"; [[ -z "$red_change" ]] || { rt="${rt:+$rt
}Change: $red_change"; red_change=""; }
  [[ -z "$rt" ]] || add_trailers "$rt"
elif (( fb_set )) && [[ -n "$change" ]]; then
  echo "commit.sh: --floor-because is for a commit without --change; with --change, ant evidence --because records the override" >&2; exit 1
elif (( fb_set )); then
  echo "commit.sh: --floor-because: no tier floor is set in .ant/config (working or HEAD's), so there is nothing to override" >&2; exit 1
fi
[[ -z "$red_change" ]] || add_trailers "Change: $red_change"

# The secret scan reads this commit's own diff: HEAD to the tree it will have,
# the named paths and nothing merely staged. A secret is in history for good
# once committed, so it runs before the gate and on --red commits as well, and
# a scanner that cannot run stops the commit rather than being skipped.
# It runs in the gate's allow-listed environment (no BASH_ENV, no exported
# function), on a diff that is text whatever the attributes say.
# SECRET_SCAN_REV names that tree, for a scanner that reads whole files: the
# working tree may already hold other bytes (S-secret-scan-001, -005).
scan="$(cconf secret_scan)" scanned=""
secret_scan(){  # <tree>
  [[ -n "$scan" ]] || return 0
  local found_rc base src=0 sout
  found_rc="$(cconf secret_scan_found_rc)"
  base="$(git rev-parse -q --verify HEAD || git hash-object -t tree /dev/null)"
  sout="$(git diff --no-relative --no-color --no-textconv --text --no-ext-diff --no-renames --src-prefix=a/ --dst-prefix=b/ "$base" "$1" | (cd "$ROOT" && gate_env_run env SECRET_SCAN_REV="$1" bash -c "$scan") 2>&1)" || src=$?
  if (( src == ${found_rc:-1} )); then
    printf '%s\n' "$sout" | tail -20 >&2
    echo "commit.sh: the secret scan found a secret in the named paths -- nothing committed" >&2
    exit 1
  elif (( src != 0 )); then
    printf '%s\n' "$sout" | tail -5 >&2
    echo "commit.sh: the secret scan could not run (rc $src): $scan -- nothing committed; install it or fix secret_scan= in .ant/config" >&2
    exit 1
  fi
  scanned="$1"
}
secret_scan "$tree"

if (( red )); then
  [[ "$(subject)" == *"(red)"* ]] || {
    echo "commit.sh --red: the subject must say (red); only the failing-test commit skips the gate" >&2
    exit 1
  }
  # S-commit-009: a red commit removes no file, and each file red_run= names
  # (working config or HEAD's: an uncommitted edit cannot drop it) has to fail.
  rr=()
  for c in "$cfg_w" "$cfg_h"; do
    v="$(sed -n 's/^red_run=//p' <<<"$c" | head -1)"
    [[ -n "$v" ]] || continue
    rrc=0; grep -qE -- "$v" </dev/null 2>/dev/null || rrc=$?
    (( rrc < 2 )) || { echo "commit.sh --red: red_run= in .ant/config does not compile" >&2; exit 1; }
    rr+=("$v")
  done
  # The list on fd 3 and the test's stdin closed: a test that reads stdin
  # would eat the names after it (tier 4 review r1).
  while IFS= read -r -d '' -u 3 f; do
    [[ -e "$ROOT/$f" || -L "$ROOT/$f" ]] || { echo "commit.sh --red: $f is removed -- a failing-test commit adds or changes tests" >&2; exit 1; }
    for v in ${rr[@]+"${rr[@]}"}; do
      grep -zqE -- "$v" < <(printf '%s\0' "$f") || continue
      if (cd "$ROOT" && gate_env_run bash -- "$f") </dev/null >/dev/null 2>&1; then
        echo "commit.sh --red: $f passes -- a failing-test commit has to fail" >&2; exit 1
      fi
      break
    done
  done 3< <(commit_files)
  red_tree="$tree"
  mode=red
elif [[ -n "$covered" ]]; then
  echo "commit.sh: gate covered by EVIDENCE layer $covered on this tree"
  mode=green
else
  mkdir -p "$LOGS"
  # one log per run: two gates at once would interleave in a shared one
  log="$LOGS/commit-gate.$$.log"
  echo "commit.sh: running the gate ($GATE) -> $log"
  if ! (cd "$ROOT" && gate_env_run bash -c "$GATE") > "$log" 2>&1; then
    tail -15 "$log" >&2
    echo "commit.sh: gate RED -- nothing committed" >&2
    exit 1
  fi
  rm -f "$log"
  mode=green
fi

# Again, after the gate: someone else may have committed while it ran, and git
# builds this commit on the HEAD it finds now. The gate read the working tree,
# which their commit came from as well, so its verdict covers the recomputed
# tree. The pass is a file per tree, so two commits at once cannot overwrite
# each other's.
tree="$(tree_now)"
# What ran is what leaves: a test that rewrote a named file (itself, to
# `exit 0`, at once or from a background job) would commit bytes nobody ran.
# Checked on this tree, the one the hook's mark binds (tier 4 review r1, r2).
[[ "$mode" != red || "$tree" == "$red_tree" ]] || { echo "commit.sh --red: a named file changed while its test ran -- nothing committed" >&2; exit 1; }
[[ -z "$change" ]] || ch_fresh "$tree"
# The gate ran on the working tree, and a named file may have changed under it:
# what is committed is this tree, so it is the one scanned (S-secret-scan-004).
[[ "$tree" == "$scanned" ]] || secret_scan "$tree"
if [[ -n "$change" ]]; then
  had="$change_fl"; change_floor
  [[ "$had" == "$change_fl" ]] || { echo "commit.sh: the commit's floor changed while the gate ran -- run it again" >&2; exit 1; }
fi
# The gate may have taken minutes: check the floor again on what is committed.
# A floor key may have been set while the gate ran: decide again.
cfg_w="$(cat "$ROOT/.ant/config" 2>/dev/null || true)"
grep -qE '^tier[34]_(paths|content)=[^[:space:]]' <<<"$cfg_w" && floors_on=1
if [[ -z "$change" ]] && (( floors_on )); then
  had="$floor_line"; plain_floor
  [[ "$had" == "$floor_line" ]] || { echo "commit.sh: the commit's floor changed while the gate ran ($had -> $floor_line) -- run it again" >&2; exit 1; }
fi
if [[ -n "$covered" && "$tree" != "$etree" ]]; then
  echo "commit.sh: HEAD moved since the EVIDENCE's tree -- nothing committed; run it again and the gate will run" >&2
  exit 1
fi
MARK="$GITDIR/precommit-ok.$tree"
printf '%s\n' "$mode" > "$MARK"
rc=0
git commit ${args[@]+"${args[@]}"} --only -- "${paths[@]}" || rc=$?
# A gate named by --gate is not the repo's gate, so it leaves no record that
# push-scope would read as one: those commits are flagged, as --no-verify's are.
if (( rc == 0 )) && [[ "$mode" == green && -z "$gate_arg" ]]; then
  mkdir -p "$LOGS/ant"
  printf 'time %s\ntree %s\ncommit %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(git rev-parse 'HEAD^{tree}')" "$(git rev-parse HEAD)" > "$LOGS/ant/last-gate.tmp"
  mv "$LOGS/ant/last-gate.tmp" "$LOGS/ant/last-gate"
fi
exit "$rc"
}
