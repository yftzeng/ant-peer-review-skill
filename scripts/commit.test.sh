#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# commit.sh + install-hook.sh: a commit lands only on a green gate.
#
# Twice a commit ran on a red gate because the gate and the commit were two
# commands joined by something other than `&&` (`| tail -3 &&`, then `;`). A
# note did not stop the second; this makes the commit itself refuse.
#
# Runs in a throwaway repo built from the scripts beside this file, so it proves
# the kit AS SHIPPED. COMMIT_GATE stands in for the repo's gate.
set -uo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T" 2>/dev/null || :' EXIT
pass=0 fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
# Each case is a string evaluated at check time.
# shellcheck disable=SC2016
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
gitc() { git -c user.email=t@example.invalid -c user.name=t "$@"; }

mkrepo() {
  local r="$T/$1"
  mkdir -p "$r/scripts"
  cp "$SRC/commit.sh" "$SRC/install-hook.sh" "$SRC/pre-commit.hook" "$r/scripts/"
  chmod +x "$r/scripts/commit.sh" "$r/scripts/install-hook.sh"
  ( cd "$r" && git init -q . && git config user.email t@example.invalid && git config user.name t ) >/dev/null 2>&1
  echo "$r"
}

R=$(mkrepo main)
cd "$R" || exit 2
n() { git rev-list --count HEAD 2>/dev/null || echo 0; }

# shellcheck disable=SC2016
check "install-hook: last line is the verdict" \
  'scripts/install-hook.sh > "$T/h1" 2>&1 && tail -1 "$T/h1" | grep -q "^install-hook: OK"'
check "install-hook: running it again is fine" 'scripts/install-hook.sh >/dev/null 2>&1'

echo a > a; git add a
check "a bare git commit is refused" '! git commit -q -m bare 2>"$T/e1" && [ "$(n)" = 0 ]'
check "and the refusal says how to commit" 'grep -q "scripts/commit.sh" "$T/e1"'
check "a red gate commits nothing" '! COMMIT_GATE=false scripts/commit.sh -q -m "feat: x" -- a >/dev/null 2>&1 && [ "$(n)" = 0 ]'
check "without paths nothing is committed, and it says to name them" \
  '! COMMIT_GATE=true scripts/commit.sh -q -m "feat: x" >/dev/null 2>"$T/e2" && [ "$(n)" = 0 ] && grep -q "name what to commit" "$T/e2"'
# @N-commit-001
check "a green gate commits" 'COMMIT_GATE=true scripts/commit.sh -q -m "feat: x" -- a >/dev/null 2>&1 && [ "$(n)" = 1 ]'
check "a green gate leaves a record of what it cleared" \
  '[ -f .ant/work/logs/ant/last-gate ] && grep -q "^tree $(git rev-parse "HEAD^{tree}")$" .ant/work/logs/ant/last-gate && [ ! -e logs ]'

# The gate comes from .ant/config when COMMIT_GATE is not set: the kit's files
# stay identical to the template, and the repo's choice lives in the repo.
mkdir -p .ant
printf 'gate=echo config-gate-ran; false\n' > .ant/config
echo b > b
check "the gate named in .ant/config is the one that runs" \
  '! scripts/commit.sh -q -m "feat: b" -- b >"$T/o1" 2>&1 && [ "$(n)" = 1 ] && grep -q config-gate-ran .ant/work/logs/commit-gate.*.log "$T/o1" 2>/dev/null'
printf 'gate=true\n' > .ant/config
check "and a green one from there commits" 'scripts/commit.sh -q -m "feat: b" -- b >/dev/null 2>&1 && [ "$(n)" = 2 ]'
rm -rf .ant

echo c > c; git add c
check "the pass is one-shot: the next bare commit is refused" '! git commit -q -m "bare again" 2>/dev/null && [ "$(n)" = 2 ]'
check "--red without (red) in the subject is refused" '! COMMIT_GATE=false scripts/commit.sh --red -q -m "test: x" -- c >/dev/null 2>&1 && [ "$(n)" = 2 ]'
check "--red with (red) commits without running the gate" \
  'printf "test: y (red)\n\nbody\n" | COMMIT_GATE=false scripts/commit.sh --red -q -F - -- c >/dev/null 2>&1 && [ "$(n)" = 3 ] && git log -1 --format=%s | grep -q "(red)"'

echo d > d; git add d
printf 'green\n' > "$(git rev-parse --git-dir)/precommit-ok.deadbeef"
check "a pass recorded for another tree does not open this one" '! git commit -q -m "stale pass" 2>/dev/null && [ "$(n)" = 3 ]'
rm -f "$(git rev-parse --git-dir)"/precommit-ok.*
git reset -q d; rm -f d

echo e1 > e; git add e; echo e2 > e
check "a named file edited after staging is committed as the gate read it" \
  'COMMIT_GATE=true scripts/commit.sh -q -m "feat: e" -- e >/dev/null 2>&1 && [ "$(n)" = 4 ] && [ "$(git show HEAD:e)" = e2 ]'
echo unrelated > u
echo f > f
check "an untracked named file is committed" \
  'COMMIT_GATE=true scripts/commit.sh -q -m "feat: f" -- f >/dev/null 2>&1 && [ "$(n)" = 5 ] && git cat-file -e HEAD:f'
git rm -q f 2>/dev/null || rm -f f
check "a deleted named file is committed as a deletion" \
  'COMMIT_GATE=true scripts/commit.sh -q -m "chore: rm f" -- f >/dev/null 2>&1 && [ "$(n)" = 6 ] && ! git cat-file -e HEAD:f 2>/dev/null'

# Two sessions can share one working tree. Their staged work stays theirs.
echo theirs > o; git add o
echo mine > m
check "another session's staged file is not committed" \
  'COMMIT_GATE=true scripts/commit.sh -q -m "feat: m" -- m >/dev/null 2>&1 && [ "$(n)" = 7 ] && ! git cat-file -e HEAD:o 2>/dev/null'
check "and it is still staged afterwards" '[ "$(git diff --cached --name-only)" = o ]'
check "a named path with nothing to commit commits nothing" \
  '! COMMIT_GATE=true scripts/commit.sh -q -m "feat: none" -- m >/dev/null 2>&1 && [ "$(n)" = 7 ]'
check "the unrelated untracked file was never touched" '[ "$(git status --porcelain u)" = "?? u" ]'
git reset -q o; rm -f o

# Another session commits while this gate runs (a gate can take minutes).
echo theirs2 > p; echo mine2 > q
check "a commit by someone else during the gate does not void this one" \
  'COMMIT_GATE="git add p && git commit -q --no-verify -m other -- p" scripts/commit.sh -q -m "feat: q" -- q >/dev/null 2>&1 && [ "$(n)" = 9 ] && git cat-file -e HEAD:q && git cat-file -e HEAD~1:p'

# --change: what leaves with the commit. The feature specs are versioned
# (specs/features/); the change's approval and EVIDENCE live in .ant/work/
# (ignored) and leave as trailers, refused when missing or stale. Fixtures are
# written by hand: commit.sh must work without the plugin, from the files
# alone (the formats `ant change` and `ant evidence` write; test/ant.test.sh
# runs the real pair end to end).
# @N-commit-002
S="$T/change"; mkdir -p "$S/scripts"
cp "$SRC/commit.sh" "$SRC/install-hook.sh" "$SRC/pre-commit.hook" "$S/scripts/"
cd "$S" || exit 2
git init -q . && git config user.email t@example.invalid && git config user.name t
printf '.ant/work/\nlogs/\n' > .gitignore; echo seed > seed
mkdir -p .ant specs/features specs/decisions; printf 'suite | 1 | pass | true\n' > .ant/gauntlet.conf
git add .gitignore seed .ant && git commit -q --no-verify -m seed
scripts/install-hook.sh >/dev/null 2>&1
start() { mkdir -p ".ant/work/$1"; git rev-parse HEAD > ".ant/work/$1/base"; }
feature() {  # <slug> <scenario ids, space separated> <revisions lines, newline separated>
  local f="specs/features/$1.md" id
  { printf '# Feature: %s\n\n```gherkin\nFeature: %s\n' "$1" "$1"
    for id in $2; do printf '  @%s\n  Scenario: %s\n    Then it holds\n' "$id" "$id"; done
    printf '```\n\n## Revisions\n%s\n' "$3"; } > "$f"
}
changed_features() {  # <change>
  { git diff --name-only "$(cat ".ant/work/$1/base")" -- specs/features; git ls-files --others --exclude-standard -- specs/features; } | sort -u
}
approve() {  # <change> <mode> [words]
  local c="$1" f
  { echo "mode $2"; [ -n "${3:-}" ] && echo "by $3"; echo "time x"
    echo "gauntlet $(git hash-object .ant/gauntlet.conf)"
    for f in $(changed_features "$c"); do [ -f "$f" ] && echo "feature $f $(git hash-object "$f")" || echo "feature $f deleted"; done
  } > ".ant/work/$c/approval"
}
evidence() {  # <change> <verdict> <scenarios> [report path] -- EVIDENCE.md bound to the working tree as it is now
  local idx tree; idx="$(mktemp)"
  GIT_INDEX_FILE="$idx" git read-tree HEAD && GIT_INDEX_FILE="$idx" git add -A -- . && tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  rm -f "$idx"
  { printf '# EVIDENCE: %s\n\n- run: 2026-10-18T00:00:00Z, tier 2, `ant evidence %s --tier 2`\n- source tree %s (HEAD x)\n' "$1" "$1" "$tree"
    printf -- '- scenarios: %s\n' "$3"
    [ -n "${4:-}" ] && printf -- '- report: %s\n' "$4"
    printf '\n| layer | tier | expect | result | rc | time | log |\n|---|---|---|---|---|---|---|\n'
    printf '| suite | 1 | pass | pass | 0 | 0s | logs/ant/x/suite.log |\n'
    printf '| e2e | 2 | pass | unavailable: no browser on this host | | | |\n\n'
    printf 'verdict: %s (1 run, 1 not run)\n' "$2"; } > ".ant/work/$1/EVIDENCE.md"
}
body() { git log -1 --format=%B; }
count() { git rev-list --count HEAD; }
refused() {  # <name> <change> <message ERE> <paths...> -- nothing committed, the reason named
  local name="$1" c="$2" re="$3"; shift 3
  local before; before="$(count)"
  if ! COMMIT_GATE=true scripts/commit.sh --change "$c" -q -m "feat: $c" -- "$@" >/dev/null 2>"$T/rf" && [ "$(count)" = "$before" ] && grep -qE -- "$re" "$T/rf"; then ok "$name"
  else bad "$name"; grep -v "^  \|staged but not named" "$T/rf" | sed 's/^/     /'; fi
}
REV1='- 2026-10-18 · +S-login-001 · decision: none -- tooling only'

# @S-commit-001
start one; echo s1 > s1; feature login "S-login-001" "$REV1"
approve one human "yes, ship it"; evidence one PASS "+S-login-001"
check "--change: approval, scenarios and evidence leave as trailers (-m)" \
  'COMMIT_GATE=true scripts/commit.sh --change one -q -m "feat: s1" -- s1 specs >/dev/null 2>"$T/c1" && body > "$T/b1" && grep -qx "Change: one" "$T/b1" && grep -qE "^Spec-approval: human \"yes, ship it\" \(specs [0-9a-f]{12}, gauntlet [0-9a-f]{12}\)$" "$T/b1" && grep -qx "Spec-scenarios: +S-login-001" "$T/b1" && grep -qx "Evidence: PASS tier 2, 1 run 1 not run" "$T/b1" && grep -qx "Evidence-not-run: e2e -- unavailable -- no browser on this host" "$T/b1" && grep -qx "Decision: none -- tooling only" "$T/b1" || { cat "$T/c1"; false; }'
check "--change: the subject is unchanged" '[ "$(git log -1 --format=%s)" = "feat: s1" ]'
start two; echo s2 > s2; feature login "S-login-001" "$REV1
- 2026-10-18 · ~S-login-001 · decision: none -- wording"
approve two auto; evidence two PASS "~S-login-001"
check "--change: an auto approval says so, and -F - keeps the body" \
  'printf "feat: s2\n\nthe body\n" | COMMIT_GATE=true scripts/commit.sh --change two -q -F - -- s2 specs >/dev/null 2>"$T/c2" && body | grep -qx "the body" && body | grep -qE "^Spec-approval: auto \(specs [0-9a-f]{12}, gauntlet" || { grep -v "^  \|staged but" "$T/c2"; false; }'

# @S-commit-002
REV3="$REV1
- 2026-10-18 · ~S-login-001 · decision: none -- wording
- 2026-10-18 · +S-login-002 · decision: none -- one more"
start three; echo s3 > s3; feature login "S-login-001 S-login-002" "$REV3"
evidence three PASS "+S-login-002"
refused "--change: an unapproved change commits nothing" three "three is not approved" s3 specs
approve three human "yes"; echo "  extra" >> specs/features/login.md
refused "--change: a feature edited after approval commits nothing" three "drifted since approval" s3 specs
feature login "S-login-001 S-login-002" "$REV3"; approve three human "yes"
printf 'suite | 1 | pass | true\nmore | 1 | pass | true\n' > .ant/gauntlet.conf
refused "--change: a gauntlet changed after approval commits nothing" three "drifted since approval" s3 specs
git checkout -q -- .ant/gauntlet.conf; feature other "S-other-001" "- 2026-10-18 · +S-other-001 · decision: none -- x"
refused "--change: a feature changed after approval and not in it commits nothing" three "drifted since approval" s3 specs
rm -f specs/features/other.md; approve three human "yes"
evidence three FAILED "+S-login-002"
refused "--change: a failed EVIDENCE commits nothing" three "no passing EVIDENCE" s3 specs
rm -f .ant/work/three/EVIDENCE.md
refused "--change: no EVIDENCE commits nothing" three "no passing EVIDENCE" s3 specs
evidence three PASS "+S-login-002"; echo s3-edited > s3
refused "--change: a named path changed since the EVIDENCE run commits nothing" three "EVIDENCE is stale for: s3" s3 specs
evidence three PASS "+S-login-002"
refused "--change: a changed feature must be committed with the change" three "specs/features/login.md.*not among the paths" s3
check "--change: a path not named (another session) does not make it stale" \
  'echo theirs > other-session-file && COMMIT_GATE=true scripts/commit.sh --change three -q -m "feat: s3" -- s3 specs >/dev/null 2>"$T/c3" && git cat-file -e HEAD:s3 && ! git cat-file -e HEAD:other-session-file 2>/dev/null || { cat "$T/c3"; false; }'
start four; echo s4 > s4; feature login "S-login-001 S-login-002" "$REV3
- 2026-10-18 · ~S-login-002"
approve four auto; evidence four PASS "~S-login-002"
refused "--change: a Revisions line must name its decision" four "D-<n> or .decision: none -- <reason>." s4 specs
feature login "S-login-001 S-login-002 S-login-003" "$REV3"; approve four auto; evidence four PASS "+S-login-003"
refused "--change: a changed feature needs a new Revisions line" four "no new Revisions line" s4 specs
feature login "S-login-001" "$REV3
- 2026-10-18 · ~S-login-001 · decision: none -- dropped two"; approve four auto; evidence four PASS "~S-login-001 -S-login-002"
refused "--change: a removed scenario is recorded in Revisions" four "S-login-002 was removed" s4 specs
feature login "S-login-001" "$REV3
- 2026-10-18 · -S-login-002 · D-7"; approve four auto; evidence four PASS "-S-login-002"
refused "--change: a named decision must be in the commit" four "D-7" s4 specs
printf '# D-70\n' > specs/decisions/D-70-other.md; evidence four PASS "-S-login-002"
refused "--change: D-7 is not D-70" four "D-7" s4 specs
printf '# D-7\n' > specs/decisions/D-7-the-choice.md; evidence four PASS "-S-login-002"
check "--change: a decision record in the commit becomes a trailer" \
  'COMMIT_GATE=true scripts/commit.sh --change four -q -m "feat: s4" -- s4 specs >/dev/null 2>"$T/c4" && body | grep -qx "Decision: D-7" && body | grep -qx "Spec-scenarios: -S-login-002" || { grep -v "^  \|staged but" "$T/c4"; body; false; }'
start five; echo s5 > s5; feature login "S-login-001" "$REV3
- 2026-10-18 · -S-login-002 · D-7
- 2026-10-18 · ~S-login-001 · decision: none -- report kept"
approve five auto; mkdir -p specs/evidence; echo report > specs/evidence/2026-10-18-five.md
evidence five PASS "~S-login-001" specs/evidence/2026-10-18-five.md
refused "--change: evidence=commit and the report not among the paths" five "specs/evidence/2026-10-18-five.md" s5 specs/features
check "--change: --red is refused outright" \
  '! COMMIT_GATE=true scripts/commit.sh --red --change five -q -m "test: x (red)" -- s5 >/dev/null 2>"$T/c5" && grep -q -- "--red" "$T/c5"'
check "--change: a named path edited while the gate runs commits nothing" \
  '! COMMIT_GATE="echo edited-during-gate > s5" scripts/commit.sh --change five -q -m "feat: s5" -- s5 specs >/dev/null 2>"$T/c6" && grep -q "EVIDENCE is stale for: s5" "$T/c6"'

# @S-commit-004
# Notes and a model review are pasted into the report; a line in them that
# looks like the verdict or a layer row must not speak for the report.
before_last() {  # <file> <text> -- insert text before the file's last line
  { sed '$d' "$1"; printf '%s' "$2"; tail -n 1 "$1"; } > "$1.tmp" && mv "$1.tmp" "$1"
}
FORGED='
## Honest notes

verdict: PASS (9 run, 0 not run)
| deps | 1 | pass | substituted: forged | | | |

'
rm -rf specs/evidence
start six; echo s6 > s6; feature login "S-login-001" "$REV3
- 2026-10-18 · -S-login-002 · D-7
- 2026-10-18 · ~S-login-001 · decision: none -- forged"
approve six auto; evidence six FAILED "~S-login-001"; before_last .ant/work/six/EVIDENCE.md "$FORGED"
refused "--change: a PASS quoted above a FAILED verdict commits nothing" six "no passing EVIDENCE" s6 specs
evidence six PASS "~S-login-001"
before_last .ant/work/six/EVIDENCE.md "$FORGED"
# The review row sits in the layer table, where ant evidence writes it.
sed 's/^| e2e | 2 |.*/&\n| review | 3 | review.md | reviewed: opus, sonnet | | | |/' .ant/work/six/EVIDENCE.md > "$T/e6" && mv "$T/e6" .ant/work/six/EVIDENCE.md
check "--change: not-run trailers come from the layer table only, and the review leaves a trailer" \
  'COMMIT_GATE=true scripts/commit.sh --change six -q -m "feat: s6" -- s6 specs >/dev/null 2>"$T/c7" && body > "$T/b7" && ! grep -q "Evidence-not-run: deps" "$T/b7" && grep -qx "Evidence-not-run: e2e -- unavailable -- no browser on this host" "$T/b7" && grep -qx "Evidence-review: opus, sonnet" "$T/b7" && grep -qx "Evidence: PASS tier 2, 1 run 1 not run" "$T/b7" || { grep -v "^  \|staged but" "$T/c7"; body; false; }'
cd "$R" || exit 2

# install-hook: the hook must RUN. Written by hand it did not: without chmod +x
# git skips it with a hint and the commit exits 0; in a worktree `.git` is a
# file; under core.hooksPath git never looks in .git/hooks at all.
refused_by_hook() {  # $1 = dir, $2 = file -- prints 1 when the hook said no
  ( cd "$1" && echo x > "$2" && git add "$2" && gitc commit -qm "$2" ) > "$T/rh" 2>&1 && { echo 0; return; }
  grep -c "commit refused" "$T/rh"
}
( gitc worktree add -q "$T/wt" ) >/dev/null 2>&1
cp -p scripts/* "$T/wt/scripts/" 2>/dev/null || { mkdir -p "$T/wt/scripts"; cp -p scripts/* "$T/wt/scripts/"; }
check "install-hook: installs from a worktree (.git is a file there)" '( cd "$T/wt" && scripts/install-hook.sh >/dev/null 2>&1 )'
check "and the worktree's bare commit is refused by it" '[ "$(refused_by_hook "$T/wt" w)" = 1 ]'
git config core.hooksPath .githooks
check "install-hook: installs under core.hooksPath" 'scripts/install-hook.sh >/dev/null 2>&1 && [ -x .githooks/pre-commit ]'
check "and that bare commit is refused by it" '[ "$(refused_by_hook "$R" h)" = 1 ]'
git config --unset core.hooksPath
printf '#!/bin/sh\necho theirs\n' > "$(git rev-parse --git-path hooks)/pre-commit"
check "install-hook: will not overwrite a hook it did not write" '! scripts/install-hook.sh >/dev/null 2>&1'
check "and leaves it as it was" '[ "$(sed -n 2p "$(git rev-parse --git-path hooks)/pre-commit")" = "echo theirs" ]'

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
