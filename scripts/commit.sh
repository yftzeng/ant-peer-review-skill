#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# Commit only on a green gate, and only the paths named.
#
#   scripts/commit.sh [git commit args] -- <path>...         gate, then commit
#   scripts/commit.sh --red [git commit args] -- <path>...   failing-test commit:
#                                                no gate, the subject says "(red)"
#   scripts/commit.sh --change <name> [git commit args] -- <path>...
#                                                gate, then commit with the change's
#                                                approval and EVIDENCE as trailers
#
# `-F -` reads the message from stdin, as with git.
#
# The gate is COMMIT_GATE, else the `gate=` line of .ant/config, else
# scripts/precommit.sh. The kit's files stay identical to the template; the
# repo's choice lives in the repo.
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
#   Evidence-review: <models>               a tier 3 review by two or more models
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
# reads it to flag commits the gate never saw.
#
# The body is one brace group ending in exit, so bash reads it whole before it
# runs: a gate takes minutes, and an edit made meanwhile must not be read at the
# old byte offset.
{
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
GITDIR="$(git rev-parse --git-dir)"
conf_gate=""
if [[ -f "$ROOT/.ant/config" ]]; then
  conf_gate="$(sed -n 's/^gate=//p' "$ROOT/.ant/config" | head -1)"
fi
GATE="${COMMIT_GATE:-${conf_gate:-scripts/precommit.sh}}"
# The kit's one sink root: logs_dir= in .ant/config, default .ant/work/logs.
LOGS=""
[[ -f "$ROOT/.ant/config" ]] && LOGS="$(sed -n 's/^logs_dir=//p' "$ROOT/.ant/config" | head -1)"
LOGS="${LOGS:-.ant/work/logs}"; [[ "$LOGS" == /* ]] || LOGS="$ROOT/$LOGS"

red=0
change=""
args=()
paths=()
tmp=""
while (( $# )); do
  case "$1" in
    --) shift; paths=("$@"); break ;;
    --red) red=1; shift ;;
    --change) change="${2:?--change needs a change name}"; shift 2 ;;
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
cconf(){ [[ -f "$ROOT/.ant/config" ]] || return 0; sed -n "s/^$1=//p" "$ROOT/.ant/config" | head -1; }
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
if [[ -n "$change" ]]; then
  (( red )) && ch_fail "a --red commit has no evidence to carry; commit the failing test without --change"
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
    layers="$(sed -n '/^| layer | tier |/,/^$/p' "$E")"
  fi
  [[ "$verdict" == "PASS ("*")" ]] || ch_fail "$change has no passing EVIDENCE -- ant evidence $change --tier N"
  etree="$(sed -n 's/^- source tree \([0-9a-f]\{40\}\).*/\1/p' "$E" | head -1)"
  { [[ -n "$etree" ]] && git cat-file -e "$etree^{tree}" 2>/dev/null; } ||
    ch_fail "$change: its EVIDENCE names no source tree this repo has -- rerun ant evidence"
  etier="$(sed -n 's/^- run: .*, tier \([123]\),.*/\1/p' "$E" | head -1)"
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
  notrun="$(sed -nE 's/^\| ([^|]+) \| [123] \| [^|]+ \| (n-a|unavailable|substituted): (.*) \| +\| +\| +\|$/Evidence-not-run: \1 -- \2 -- \3/p' <<<"$layers")"
  [[ -z "$notrun" ]] || trailers="$trailers
$notrun"
  review="$(sed -nE 's/^\| review \| 3 \| review\.md \| reviewed: ([^|]*[^| ]) +\|.*/Evidence-review: \1/p' <<<"$layers")"
  [[ -z "$review" ]] || trailers="$trailers
$review"
  for d in $dec_ids; do trailers="$trailers
Decision: $d"; done
  while IFS= read -r n; do [[ -z "$n" ]] || trailers="$trailers
Decision: $n"; done <<<"$nones"
  ch_fresh "$tree"
  # The message: every -m paragraph and -F file, then the trailers in their
  # own last paragraph (`git commit --trailer` needs git 2.32).
  msgf="$(mktemp)" rest=() i=0
  while (( i < ${#args[@]} )); do
    case "${args[$i]}" in
      -m) printf '%s\n\n' "${args[$((i + 1))]:-}" >> "$msgf"; i=$((i + 2)) ;;
      -F) cat "${args[$((i + 1))]}" >> "$msgf"; i=$((i + 2)) ;;
      *) rest+=("${args[$i]}"); i=$((i + 1)) ;;
    esac
  done
  [[ -s "$msgf" ]] || ch_fail "--change needs the message as -m or -F"
  awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] ~ /^[[:space:]]*$/) n--; for (i = 1; i <= n; i++) print l[i] }' "$msgf" > "$msgf.body"
  { cat "$msgf.body"; printf '\n%s\n' "$trailers"; } > "$msgf"
  rm -f "$msgf.body"
  args=(${rest[@]+"${rest[@]}"} -F "$msgf")
fi

if (( red )); then
  [[ "$(subject)" == *"(red)"* ]] || {
    echo "commit.sh --red: the subject must say (red); only the failing-test commit skips the gate" >&2
    exit 1
  }
  mode=red
else
  mkdir -p "$LOGS"
  # one log per run: two gates at once would interleave in a shared one
  log="$LOGS/commit-gate.$$.log"
  echo "commit.sh: running the gate ($GATE) -> $log"
  if ! (cd "$ROOT" && bash -c "$GATE") > "$log" 2>&1; then
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
[[ -z "$change" ]] || ch_fresh "$tree"
MARK="$GITDIR/precommit-ok.$tree"
printf '%s\n' "$mode" > "$MARK"
rc=0
git commit ${args[@]+"${args[@]}"} --only -- "${paths[@]}" || rc=$?
if (( rc == 0 )) && [[ "$mode" == green ]]; then
  mkdir -p "$LOGS/ant"
  printf 'time %s\ntree %s\ncommit %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(git rev-parse 'HEAD^{tree}')" "$(git rev-parse HEAD)" > "$LOGS/ant/last-gate.tmp"
  mv "$LOGS/ant/last-gate.tmp" "$LOGS/ant/last-gate"
fi
exit "$rc"
}
