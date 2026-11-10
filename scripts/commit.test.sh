#!/usr/bin/env bash
# Part of the ant-mode kit -- the last line is the verdict.
# commit.sh + install-hook.sh: a commit lands only on a green gate.
#
# Twice a commit ran on a red gate because the gate and the commit were two
# commands joined by something other than `&&` (`| tail -3 &&`, then `;`). A
# note did not stop the second; this makes the commit itself refuse.
#
# Runs in a throwaway repo built from the scripts beside this file, so it proves
# the kit AS SHIPPED. --gate stands in for the repo's gate.
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
check "a red gate commits nothing" '! scripts/commit.sh --gate false -q -m "feat: x" -- a >/dev/null 2>&1 && [ "$(n)" = 0 ]'
check "without paths nothing is committed, and it says to name them" \
  '! scripts/commit.sh --gate true -q -m "feat: x" >/dev/null 2>"$T/e2" && [ "$(n)" = 0 ] && grep -q "name what to commit" "$T/e2"'
# @N-commit-001
check "a green gate commits" 'scripts/commit.sh --gate true -q -m "feat: x" -- a >/dev/null 2>&1 && [ "$(n)" = 1 ]'
# @S-commit-010
check "a gate named by --gate leaves no record of a green gate" '[ ! -e .ant/work/logs/ant/last-gate ]'

# The gate comes from .ant/config when --gate is not given: the kit's files
# stay identical to the template, and the repo's choice lives in the repo.
mkdir -p .ant
printf 'gate=echo config-gate-ran; false\n' > .ant/config
echo b > b
check "the gate named in .ant/config is the one that runs" \
  '! scripts/commit.sh -q -m "feat: b" -- b >"$T/o1" 2>&1 && [ "$(n)" = 1 ] && grep -q config-gate-ran .ant/work/logs/commit-gate.*.log "$T/o1" 2>/dev/null'
printf 'gate=true\n' > .ant/config
check "and a green one from there commits" 'scripts/commit.sh -q -m "feat: b" -- b >/dev/null 2>&1 && [ "$(n)" = 2 ]'
check "a green gate leaves a record of what it cleared" \
  '[ -f .ant/work/logs/ant/last-gate ] && grep -q "^tree $(git rev-parse "HEAD^{tree}")$" .ant/work/logs/ant/last-gate && [ ! -e logs ]'
rm -rf .ant

echo c > c; git add c
check "the pass is one-shot: the next bare commit is refused" '! git commit -q -m "bare again" 2>/dev/null && [ "$(n)" = 2 ]'
check "--red without (red) in the subject is refused" '! scripts/commit.sh --gate false --red -q -m "test: x" -- c >/dev/null 2>&1 && [ "$(n)" = 2 ]'
check "--red with (red) commits without running the gate" \
  'printf "test: y (red)\n\nbody\n" | scripts/commit.sh --gate false --red -q -F - -- c >/dev/null 2>&1 && [ "$(n)" = 3 ] && git log -1 --format=%s | grep -q "(red)"'

echo d > d; git add d
printf 'green\n' > "$(git rev-parse --git-dir)/precommit-ok.deadbeef"
check "a pass recorded for another tree does not open this one" '! git commit -q -m "stale pass" 2>/dev/null && [ "$(n)" = 3 ]'
rm -f "$(git rev-parse --git-dir)"/precommit-ok.*
git reset -q d; rm -f d

echo e1 > e; git add e; echo e2 > e
check "a named file edited after staging is committed as the gate read it" \
  'scripts/commit.sh --gate true -q -m "feat: e" -- e >/dev/null 2>&1 && [ "$(n)" = 4 ] && [ "$(git show HEAD:e)" = e2 ]'
echo unrelated > u
echo f > f
check "an untracked named file is committed" \
  'scripts/commit.sh --gate true -q -m "feat: f" -- f >/dev/null 2>&1 && [ "$(n)" = 5 ] && git cat-file -e HEAD:f'
git rm -q f 2>/dev/null || rm -f f
check "a deleted named file is committed as a deletion" \
  'scripts/commit.sh --gate true -q -m "chore: rm f" -- f >/dev/null 2>&1 && [ "$(n)" = 6 ] && ! git cat-file -e HEAD:f 2>/dev/null'

# Two sessions can share one working tree. Their staged work stays theirs.
echo theirs > o; git add o
echo mine > m
check "another session's staged file is not committed" \
  'scripts/commit.sh --gate true -q -m "feat: m" -- m >/dev/null 2>&1 && [ "$(n)" = 7 ] && ! git cat-file -e HEAD:o 2>/dev/null'
check "and it is still staged afterwards" '[ "$(git diff --cached --name-only)" = o ]'
check "a named path with nothing to commit commits nothing" \
  '! scripts/commit.sh --gate true -q -m "feat: none" -- m >/dev/null 2>&1 && [ "$(n)" = 7 ]'
check "the unrelated untracked file was never touched" '[ "$(git status --porcelain u)" = "?? u" ]'
git reset -q o; rm -f o

# Another session commits while this gate runs (a gate can take minutes).
echo theirs2 > p; echo mine2 > q
check "a commit by someone else during the gate does not void this one" \
  'scripts/commit.sh --gate "git add p && git commit -q --no-verify -m other -- p" -q -m "feat: q" -- q >/dev/null 2>&1 && [ "$(n)" = 9 ] && git cat-file -e HEAD:q && git cat-file -e HEAD~1:p'

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
  if ! scripts/commit.sh --gate true --change "$c" -q -m "feat: $c" -- "$@" >/dev/null 2>"$T/rf" && [ "$(count)" = "$before" ] && grep -qE -- "$re" "$T/rf"; then ok "$name"
  else bad "$name"; grep -v "^  \|staged but not named" "$T/rf" | sed 's/^/     /'; fi
}
REV1='- 2026-10-18 · +S-login-001 · decision: none -- tooling only'

# @S-commit-001
start one; echo s1 > s1; feature login "S-login-001" "$REV1"
approve one human "yes, ship it"; evidence one PASS "+S-login-001"
check "--change: approval, scenarios and evidence leave as trailers (-m)" \
  'scripts/commit.sh --gate true --change one -q -m "feat: s1" -- s1 specs >/dev/null 2>"$T/c1" && body > "$T/b1" && grep -qx "Change: one" "$T/b1" && grep -qE "^Spec-approval: human \"yes, ship it\" \(specs [0-9a-f]{12}, gauntlet [0-9a-f]{12}\)$" "$T/b1" && grep -qx "Spec-scenarios: +S-login-001" "$T/b1" && grep -qx "Evidence: PASS tier 2, 1 run 1 not run" "$T/b1" && grep -qx "Evidence-not-run: e2e -- unavailable -- no browser on this host" "$T/b1" && grep -qx "Decision: none -- tooling only" "$T/b1" || { cat "$T/c1"; false; }'
check "--change: the subject is unchanged" '[ "$(git log -1 --format=%s)" = "feat: s1" ]'
start two; echo s2 > s2; feature login "S-login-001" "$REV1
- 2026-10-18 · ~S-login-001 · decision: none -- wording"
approve two auto; evidence two PASS "~S-login-001"
check "--change: an auto approval says so, and -F - keeps the body" \
  'printf "feat: s2\n\nthe body\n" | scripts/commit.sh --gate true --change two -q -F - -- s2 specs >/dev/null 2>"$T/c2" && body | grep -qx "the body" && body | grep -qE "^Spec-approval: auto \(specs [0-9a-f]{12}, gauntlet" || { grep -v "^  \|staged but" "$T/c2"; false; }'

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
  'echo theirs > other-session-file && scripts/commit.sh --gate true --change three -q -m "feat: s3" -- s3 specs >/dev/null 2>"$T/c3" && git cat-file -e HEAD:s3 && ! git cat-file -e HEAD:other-session-file 2>/dev/null || { cat "$T/c3"; false; }'
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
  'scripts/commit.sh --gate true --change four -q -m "feat: s4" -- s4 specs >/dev/null 2>"$T/c4" && body | grep -qx "Decision: D-7" && body | grep -qx "Spec-scenarios: -S-login-002" || { grep -v "^  \|staged but" "$T/c4"; body; false; }'
start five; echo s5 > s5; feature login "S-login-001" "$REV3
- 2026-10-18 · -S-login-002 · D-7
- 2026-10-18 · ~S-login-001 · decision: none -- report kept"
approve five auto; mkdir -p specs/evidence; echo report > specs/evidence/2026-10-18-five.md
evidence five PASS "~S-login-001" specs/evidence/2026-10-18-five.md
refused "--change: evidence=commit and the report not among the paths" five "specs/evidence/2026-10-18-five.md" s5 specs/features
# @S-commit-008 -- reversed 2026-10-27: "--change: --red is refused outright".
# A red commit names its change, so push-scope can credit it to the change's
# evidence commit; it carries no evidence of its own.
mkdir -p tests; echo t > tests/red_t5
check "--change: --red --change carries Change: <name> and nothing else of the change" \
  'scripts/commit.sh --gate false --red --change five -q -m "test: t5 (red)" -- tests/red_t5 >/dev/null 2>"$T/c5" && grep -qx "Change: five" <<<"$(body)" && ! grep -qE "^(Evidence|Spec-|Decision)" <<<"$(body)" || { cat "$T/c5"; body; false; }'
echo t2 > tests/red_t5
check "--change: --red --change with no such change is refused" \
  '! scripts/commit.sh --gate false --red --change no-such -q -m "test: t5 (red)" -- tests/red_t5 >/dev/null 2>"$T/c5b" && grep -q "no-such" "$T/c5b"'
git checkout -q -- tests/red_t5 2>/dev/null || :
# Round 1 (fable, opus): with --floor-because too, both trailers are one block
# git reads as trailers (a second block was not).
printf 'tier3_paths=^tests/red_f\nred_paths=^tests/\n' > .ant/config; echo f > tests/red_f6
check "--change: --red --change with --floor-because keeps every trailer in git's trailer block" \
  'scripts/commit.sh --gate false --red --change five --floor-because "a floored test" -q -m "test: f6 (red)" -- tests/red_f6 >/dev/null 2>"$T/c5c" && t="$(git log -1 --format="%(trailers:only)")" && grep -qx "Change: five" <<<"$t" && grep -q "^Floor-override: " <<<"$t" || { cat "$T/c5c"; body; false; }'
rm -f .ant/config
check "--change: a named path edited while the gate runs commits nothing" \
  '! scripts/commit.sh --gate "echo edited-during-gate > s5" --change five -q -m "feat: s5" -- s5 specs >/dev/null 2>"$T/c6" && grep -q "EVIDENCE is stale for: s5" "$T/c6"'

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
sed -e 's/^| e2e | 2 |.*/&\n| review | 4 | review.md | reviewed: astra, fable (author opus) | | | |\n| cross-vendor | 4 | review.md | unavailable: no OpenAI here | | | |\n| rounds | 4 | review.md | under the minimum (2 < 3): fixes after the last round were not re-reviewed | | | |\n| unverified fixes | 4 | review.md | unverified: the cap check moved after round 2 | | | |/' -e 's/, tier 2, `ant evidence/, tier 4, `ant evidence/' -e 's/^- run: .*/&\n- review usage: astra US$0.82; fable 232,289 tok/' .ant/work/six/EVIDENCE.md > "$T/e6" && mv "$T/e6" .ant/work/six/EVIDENCE.md
before_last .ant/work/six/EVIDENCE.md $'\n## Honest notes\n- review usage: NOTES-FORGED-USAGE\n'
check "--change: not-run trailers come from the layer table only, and the review leaves a trailer" \
  'scripts/commit.sh --gate true --change six -q -m "feat: s6" -- s6 specs >/dev/null 2>"$T/c7" && body > "$T/b7" && ! grep -q "Evidence-not-run: deps" "$T/b7" && grep -qx "Evidence-not-run: e2e -- unavailable -- no browser on this host" "$T/b7" && grep -qx "Evidence-review: astra, fable (author opus)" "$T/b7" && grep -qx "Evidence-review-usage: astra US\$0.82; fable 232,289 tok" "$T/b7" && ! grep -q "NOTES-FORGED-USAGE" "$T/b7" && grep -qx "Evidence-not-run: cross-vendor -- unavailable -- no OpenAI here" "$T/b7" && grep -qx "Evidence: PASS tier 4, 1 run 1 not run" "$T/b7" && grep -qx "Evidence-rounds: 2 < 3 -- fixes after the last round were not re-reviewed" "$T/b7" && grep -qx "Evidence-unverified: the cap check moved after round 2" "$T/b7" || { grep -v "^  \|staged but" "$T/c7"; body; false; }'
# With no usage in the header, a usage line in the notes is still not a trailer.
start seven; echo s7 > s7; approve seven auto; evidence seven PASS "none"
before_last .ant/work/seven/EVIDENCE.md $'\n## Honest notes\n- review usage: NOTES-ONLY-USAGE\n'
check "--change: a usage line in the notes alone leaves no usage trailer" \
  'scripts/commit.sh --gate true --change seven -q -m "feat: s7" -- s7 >/dev/null 2>"$T/c8" && body > "$T/b8" && ! grep -q "Evidence-review-usage" "$T/b8" || { grep -v "^  \|staged but" "$T/c8"; body; false; }'
# @S-evidence-011
start ten; echo s10 > s10; approve ten auto; evidence ten PASS "none"
# The override names a file of this commit (S-commit-006: else it stays out).
sed 's/^- scenarios: none$/&\n- tier override: 2 below floor 4 (s10): a comment only/' .ant/work/ten/EVIDENCE.md > "$T/e10" && mv "$T/e10" .ant/work/ten/EVIDENCE.md
check "--change: a tier override in the EVIDENCE leaves as a trailer" \
  'scripts/commit.sh --gate true --change ten -q -m "feat: s10" -- s10 >/dev/null 2>"$T/c10" && body | grep -qx "Evidence-tier-override: 2 below floor 4 (s10): a comment only" || { cat "$T/c10"; body; false; }'

start ten2; echo s10b > s10b; approve ten2 auto; evidence ten2 PASS "none"
sed 's/^- scenarios: none$/&\n- tier override: 2 below floor 4 (theirs\/auth.py): another session/' .ant/work/ten2/EVIDENCE.md > "$T/e10b" && mv "$T/e10b" .ant/work/ten2/EVIDENCE.md
check "--change: an override naming a file this commit does not carry stays out" \
  'scripts/commit.sh --gate true --change ten2 -q -m "feat: s10b" -- s10b >/dev/null 2>"$T/c10b" && ! body | grep -q "Evidence-tier-override" && grep -q "does not carry" "$T/c10b" || { cat "$T/c10b"; body; false; }'

# @S-evidence-014
start sec1; echo sec1 > sec1; approve sec1 auto; evidence sec1 PASS "none"
sed 's/^| e2e | 2 |.*/&\n| security | 3 | review.md | checked: security-review (classes: authz) | | | |/' .ant/work/sec1/EVIDENCE.md > "$T/esec" && mv "$T/esec" .ant/work/sec1/EVIDENCE.md
check "--change: the security lens leaves as a trailer" \
  'scripts/commit.sh --gate true --change sec1 -q -m "feat: sec1" -- sec1 >/dev/null 2>"$T/csec" && body | grep -qx "Evidence-security: security-review (classes: authz)" || { cat "$T/csec"; body; false; }'

# @S-commit-006
# The commit's own files decide its floor, read from the working .ant/config
# and HEAD's; an EVIDENCE run at a lower tier needs the override line.
cp .ant/config "$T/cfg6" 2>/dev/null || : > "$T/cfg6"
printf 'tier4_paths=^auth/\n' >> .ant/config
start eleven; mkdir -p auth; echo s11 > auth/s11; approve eleven auto; evidence eleven PASS "none"
refused "--change: an EVIDENCE below the floor of a named path commits nothing" eleven "EVIDENCE tier 2 is below the floor 4 set by auth/s11" auth/s11
sed 's/^- scenarios: none$/&\n- tier override: 2 below floor 4 (auth\/s11): a comment only/' .ant/work/eleven/EVIDENCE.md > "$T/e11" && mv "$T/e11" .ant/work/eleven/EVIDENCE.md
check "--change: with the override line it commits" \
  'scripts/commit.sh --gate true --change eleven -q -m "feat: s11" -- auth/s11 >/dev/null 2>"$T/c11" && body | grep -qx "Evidence-tier-override: 2 below floor 4 (auth/s11): a comment only" || { cat "$T/c11"; false; }'
# Without --change a floored file needs a named override; --red names tests only.
printf 'tests=^tests/\n' >> .ant/config
echo s12 > auth/s12
check "plain: a named path with a floor of 3 or more needs --change" \
  '! scripts/commit.sh --gate true -q -m "chore: s12" -- auth/s12 >/dev/null 2>"$T/c12" && grep -q "needs --change" "$T/c12" && ! git cat-file -e HEAD:auth/s12 2>/dev/null'
check "plain: --floor-because commits it and leaves a Floor-override trailer" \
  'scripts/commit.sh --gate true --floor-because "typo in a comment" -q -m "chore: s12" -- auth/s12 >/dev/null 2>"$T/c13" && body | grep -qx "Floor-override: 4 (auth/s12): typo in a comment" || { cat "$T/c13"; body; false; }'
echo s14 > auth/s14
check "red: a --red commit naming a file outside tests= is refused" \
  '! scripts/commit.sh --gate false --red -q -m "test: x (red)" -- auth/s14 >/dev/null 2>"$T/c14" && grep -q "tests=" "$T/c14"'
mkdir -p tests; echo t > tests/t14
check "red: a --red commit of test files still lands without the gate" \
  'scripts/commit.sh --gate false --red -q -m "test: t14 (red)" -- tests/t14 >/dev/null 2>"$T/c15" || { cat "$T/c15"; false; }'
rm -f auth/s14
# Round 3: --red is floored too; it may carry specs and the spec index; tests=
# unset falls back to the plugin's default; the floor is checked again on the
# tree actually committed; an override for a lower floor does not count.
printf 'tests=^tests/\ntier4_paths=^auth/|^tests/secure|^zone/secret\n' > .ant/config
echo t > tests/secure_t
check "red: a floored test file needs --floor-because" \
  '! scripts/commit.sh --gate false --red -q -m "test: secure (red)" -- tests/secure_t >/dev/null 2>"$T/c16" && grep -q -- "--floor-because" "$T/c16" && scripts/commit.sh --gate false --red --floor-because "mod tests in a floored file" -q -m "test: secure (red)" -- tests/secure_t >/dev/null 2>&1'
mkdir -p specs/features; echo f > specs/features/red.md; echo t2 > tests/t16
check "red: a failing-test commit may carry its feature spec" \
  'scripts/commit.sh --gate false --red -q -m "test: t16 (red)" -- tests/t16 specs/features/red.md >/dev/null 2>"$T/c17" || { cat "$T/c17"; false; }'
printf 'tier4_paths=^auth/|^zone/secret\n' > .ant/config
mkdir -p src; echo a > src/app.py; echo b > src/app_test.py
check "red: with tests= unset the plugin's default applies, not anything" \
  '! scripts/commit.sh --gate false --red -q -m "test: x (red)" -- src/app.py >/dev/null 2>"$T/c18" && scripts/commit.sh --gate false --red -q -m "test: y (red)" -- src/app_test.py >/dev/null 2>&1'
rm -f src/app.py; echo s19 > auth/s19
check "plain: --floor-because with an empty message is refused" \
  '! scripts/commit.sh --gate true --floor-because "typo" -q -m "" -- auth/s19 >/dev/null 2>"$T/c19" && ! git cat-file -e HEAD:auth/s19 2>/dev/null'
rm -f auth/s19; mkdir -p zone; echo z > zone/plain
check "plain: a floored file that appears while the gate runs is caught on the committed tree" \
  '! scripts/commit.sh --gate "echo x > zone/secret" -q -m "chore: zone" -- zone >/dev/null 2>"$T/c20" && grep -q "needs --change" "$T/c20" && ! git cat-file -e HEAD:zone/secret 2>/dev/null'
rm -rf zone
printf 'tier3_content=require_admin\\(\ncontent_scope=\\.py$\n' > .ant/config; mkdir -p api; printf 'require_admin(user)\n' > api/r.py
check "plain: an inherited _floor_revs does not silence the content floor" \
  '! _floor_revs=4b825dc642cb6eb9a060e54bf8d69288fbee4904 scripts/commit.sh --gate true -q -m "feat: r" -- api/r.py >/dev/null 2>"$T/c30" && grep -q "tier floor" "$T/c30"'
rm -rf api; printf 'tier4_paths=^auth/|^zone/secret\n' > .ant/config
start twelve; echo s20 > auth/s20; approve twelve auto; evidence twelve PASS "none"
sed 's/^- scenarios: none$/&\n- tier override: 2 below floor 3 (auth\/s20): an old floor/' .ant/work/twelve/EVIDENCE.md > "$T/e20" && mv "$T/e20" .ant/work/twelve/EVIDENCE.md
refused "--change: an override granted for a lower floor does not count" twelve "below the floor 4" auth/s20
rm -f auth/s20
# Round 4.
git add .ant/config 2>/dev/null; printf 'tier4_paths=^auth/|^zone/secret\ntier3_paths=^zone/\nred_paths=^tests/\n' > .ant/config
git add .ant/config && git commit -q --no-verify -m "policy in HEAD"
mkdir -p src; echo a > src/app2_test.py
sed 's/^red_paths=.*/red_paths=./' .ant/config > "$T/cf" && cp "$T/cf" .ant/config
check "red: an uncommitted red_paths cannot widen what HEAD allows" \
  '! scripts/commit.sh --gate false --red -q -m "test: w (red)" -- src/app2_test.py >/dev/null 2>"$T/c21" && ! git cat-file -e HEAD:src/app2_test.py 2>/dev/null'
git checkout -q -- .ant/config; rm -f src/app2_test.py
echo a > src/app3_spec.rs
check "red: a file outside red_paths is refused even with --floor-because" \
  '! scripts/commit.sh --gate false --red --floor-because "it has a mod tests" -q -m "test: r (red)" -- src/app3_spec.rs >/dev/null 2>"$T/c22"'
rm -f src/app3_spec.rs
mkdir -p zone; echo p > zone/plain; git add zone/plain; git commit -q --no-verify -m zone; echo p2 > zone/plain
echo s0 > zone/secret; git add zone/secret; git commit -q --no-verify -m secret
check "plain: a floor that rises during the gate stops the commit (no stale trailer)" \
  '! scripts/commit.sh --gate "echo s1 > zone/secret" --floor-because "typo in a comment" -q -m "chore: zone" -- zone >/dev/null 2>"$T/c23" && grep -q "while the gate ran" "$T/c23" || { cat "$T/c23"; false; }'
git checkout -q -- zone
# Round 5.
git checkout -q HEAD -- zone; echo s3 > zone/secret
check "plain: a floor that drops to none during the gate stops the commit (no stale trailer)" \
  '! scripts/commit.sh --gate "git checkout -q HEAD -- zone/secret" --floor-because "typo in a comment" -q -m "chore: zone" -- zone >/dev/null 2>"$T/c25" && grep -q "while the gate ran" "$T/c25" || { cat "$T/c25"; false; }'
git checkout -q -- zone
mkdir -p tests; echo t > tests/secure_t2; printf 'tier4_paths=^auth/|^tests/secure|^zone/secret\ntier3_paths=^zone/\nred_paths=^tests/\n' > .ant/config
check "red: a floored red file is told about --floor-because, not --change" \
  '! scripts/commit.sh --gate false --red -q -m "test: s (red)" -- tests/secure_t2 >/dev/null 2>"$T/c26" && grep -q -- "--floor-because" "$T/c26" && ! grep -q -- "--change" "$T/c26"'
sed 's/^red_paths=.*/red_paths=(/' .ant/config > "$T/cf" && cp "$T/cf" .ant/config
check "red: a red_paths that does not compile says so" \
  '! scripts/commit.sh --gate false --red -q -m "test: s (red)" -- tests/secure_t2 >/dev/null 2>"$T/c27" && grep -q "red_paths .*does not compile" "$T/c27"'
git checkout -q -- .ant/config; rm -f tests/secure_t2
start thirteen; mkdir -p auth; echo a > auth/a13; echo b > auth/b13; approve thirteen auto; evidence thirteen PASS "none"
sed 's/^- scenarios: none$/&\n- tier override: 2 below floor 4 (auth\/a13): a comment only/' .ant/work/thirteen/EVIDENCE.md > "$T/e13" && mv "$T/e13" .ant/work/thirteen/EVIDENCE.md
refused "--change: an override for a file the commit does not carry does not count" thirteen "below the floor 4" auth/b13
rm -f auth/a13 auth/b13
check "plain: --floor-because with no reason says so" \
  '! scripts/commit.sh -q -m x --floor-because >/dev/null 2>"$T/c24" && grep -q -- "--floor-because" "$T/c24"'
# A floor introduced while the gate runs is caught too.
printf 'gate=true\n' > .ant/config; git add .ant/config; git commit -q --no-verify -m "no floors"
mkdir -p auth; echo i > auth/intro; git add auth/intro; git commit -q --no-verify -m intro; echo i2 > auth/intro
check "plain: a floor set while the gate runs is checked after it" \
  '! scripts/commit.sh --gate "echo tier4_paths=^auth/ >> .ant/config" -q -m "chore: intro" -- auth/intro >/dev/null 2>"$T/c28" && ! git log -1 --format=%s | grep -q "chore: intro" || { cat "$T/c28"; false; }'
git checkout -q -- auth/intro .ant/config
check "plain: --floor-because where no floor is set says that" \
  '! scripts/commit.sh --gate true --floor-because why -q -m x -- auth/intro >/dev/null 2>"$T/c29" && grep -q "no tier floor" "$T/c29"'
cp "$T/cfg6" .ant/config

# @S-commit-005
# The EVIDENCE's ci layer already ran the gate's checks on this exact tree. The
# gate is `false`, named in .ant/config as a repo's gate is, so a commit that
# lands proves the gate did not run. Earlier cases leave files behind; the
# EVIDENCE tree is the whole working tree, so settle it first or no tree could
# equal it.
printf 'gate=false\ngate_covered_by=suite\n' > .ant/config; git add -A . && git commit -q --no-verify -m "settle the fixture"
start eight; echo s8 > s8; approve eight auto; evidence eight PASS "none"
check "--change: a gate the EVIDENCE ran on this tree is not run again" \
  'scripts/commit.sh --change eight -q -m "feat: s8" -- s8 >"$T/o8" 2>&1 && git cat-file -e HEAD:s8 && grep -q "gate covered by EVIDENCE layer suite on this tree" "$T/o8" || { cat "$T/o8"; false; }'
start nine; echo s9 > s9; echo theirs9 > other9; approve nine auto; evidence nine PASS "none"
check "--change: a committed tree other than the EVIDENCE's runs the gate" \
  '! scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o9" && grep -q "gate RED" "$T/o9" && ! git cat-file -e HEAD:s9 2>/dev/null'
rm -f other9; evidence nine PASS "none"
check "--change: a gate named by --gate is not the one the layers cover, so it runs" \
  '! scripts/commit.sh --gate false --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o14" && grep -q "gate RED" "$T/o14"'
# The gate keys are read only when they match HEAD's (S-commit-011), so each
# case commits its config as a fixture, and the EVIDENCE is taken again on
# the tree that now carries it.
setconf(){ printf "$1" > .ant/config; git commit -q --no-verify -m "fixture: config" -- .ant/config; }
setconf 'gate=false\ngate_covered_by=e2e\n'; evidence nine PASS "none"
check "--change: a covering layer that did not pass runs the gate" \
  '! scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o10" && grep -q "gate RED" "$T/o10"'
cp .ant/work/nine/EVIDENCE.md "$T/e9"
before_last .ant/work/nine/EVIDENCE.md $'\n## Notes\n\n| layer | tier | expect | result | rc | time | log |\n|---|---|---|---|---|---|---|\n| e2e | 2 | pass | pass | 0 | 1s | old-e2e.log |\n\n'
check "--change: a layer table quoted in the notes cannot cover the gate" \
  '! scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o15" && grep -q "gate RED" "$T/o15"'
cp "$T/e9" .ant/work/nine/EVIDENCE.md
setconf 'gate=false\ngate_covered_by=suite e2e\n'; evidence nine PASS "none"
check "--change: with several covering layers, one that did not pass runs the gate" \
  '! scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o12" && grep -q "gate RED" "$T/o12"'
setconf 'gate=false\ngate_covered_by=suite suite\n'; evidence nine PASS "none"
check "--change: with several covering layers, all passed, the gate is not run" \
  'scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >"$T/o13" 2>&1 && grep -q "gate covered by EVIDENCE layer suite suite on this tree" "$T/o13" || { cat "$T/o13"; false; }'
git reset -q --soft HEAD~1 && git reset -q && evidence nine PASS "none"
setconf 'gate=false\n'; evidence nine PASS "none"
check "--change: without gate_covered_by the gate runs" \
  '! scripts/commit.sh --change nine -q -m "feat: s9" -- s9 >/dev/null 2>"$T/o11" && grep -q "gate RED" "$T/o11"'
git checkout -q -- .ant/config

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

# @N-commit-003
# Retroactive security review (opus, 2026-10-27): an exported MAKEFLAGS=i
# made make ignore every failing recipe, so a red make-based gate passed.
printf 'gate:\n\tfalse\n' > gate.mk; echo m > mf
check "an exported MAKEFLAGS does not turn a red make gate green" \
  '! MAKEFLAGS=i scripts/commit.sh --gate "make -s -f gate.mk gate" -q -m "feat: mf" -- mf >/dev/null 2>&1 && ! git log -1 --format=%s | grep -q "feat: mf"'
rm -f gate.mk mf
echo g > gf; printf 'gate:\n\tfalse\n' > gate.mk
check "an exported GNUMAKEFLAGS does not turn a red make gate green" \
  '! GNUMAKEFLAGS=i scripts/commit.sh --gate "make -s -f gate.mk gate" -q -m "feat: gf" -- gf >/dev/null 2>&1 && ! git log -1 --format=%s | grep -q "feat: gf"'
check "a variable the allow-list does not name never reaches the gate" \
  'PROBE_GATE_ENV=1 scripts/commit.sh --gate "[ -z \"\${PROBE_GATE_ENV:-}\" ]" -q -m "feat: gf" -- gf >/dev/null 2>&1 && git log -1 --format=%s | grep -q "feat: gf"'
rm -f gate.mk

# @S-commit-009
# Backlog P3 (2026-10-27): red_paths admits every *.test.sh, so a gate's own
# test changed to `exit 0` could leave as (red) -- nothing ran it.
R9=$(mkrepo red9); cd "$R9" || exit 2
mkdir -p tests; echo a > a; scripts/commit.sh --gate true -q -m "chore: base" -- a >/dev/null 2>&1
printf 'red_paths=^tests/\nred_run=\\.test\\.sh$\n' > .ant/config
scripts/commit.sh --gate true -q -m "chore: config" -- .ant/config >/dev/null 2>&1
nr() { git rev-list --count HEAD; }
printf 'exit 0\n' > tests/g.test.sh
check "red: a red_run test that passes commits nothing, and says so" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: g (red)" -- tests/g.test.sh >/dev/null 2>"$T/r9a" && [ "$(nr)" = "$b" ] && grep -q "tests/g.test.sh passes" "$T/r9a"'
printf 'exit 1\n' > tests/g.test.sh
check "red: a red_run test that fails commits as before" \
  'scripts/commit.sh --gate true --red -q -m "test: g (red)" -- tests/g.test.sh >/dev/null 2>"$T/r9b" || { cat "$T/r9b"; false; }'
printf '[ -z "${PROBE_RED_ENV:-}" ]\n' > tests/e.test.sh
check "red: the test runs in the gate's environment, not the caller's" \
  'b="$(nr)"; ! PROBE_RED_ENV=1 scripts/commit.sh --gate true --red -q -m "test: e (red)" -- tests/e.test.sh >/dev/null 2>&1 && [ "$(nr)" = "$b" ]'
printf 'exit 0\n' > tests/other_test.py
check "red: a file red_run does not name is not run" \
  'scripts/commit.sh --gate true --red -q -m "test: p (red)" -- tests/other_test.py >/dev/null 2>&1'
git rm -q --cached tests/g.test.sh; rm -f tests/g.test.sh
check "red: a red commit removes no test" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: rm (red)" -- tests/g.test.sh >/dev/null 2>"$T/r9c" && [ "$(nr)" = "$b" ] && grep -q "tests/g.test.sh is removed" "$T/r9c"'
git reset -q HEAD -- tests/g.test.sh; git checkout -q -- tests/g.test.sh
printf 'red_paths=^tests/\n' > .ant/config; printf 'exit 0\n' > tests/g.test.sh
check "red: an uncommitted edit that drops red_run does not stop HEAD's from running" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: g2 (red)" -- tests/g.test.sh >/dev/null 2>&1 && [ "$(nr)" = "$b" ]'
printf 'cat >/dev/null; exit 1\n' > tests/a.test.sh; printf 'exit 0\n' > tests/z.test.sh
check "red: a test that reads stdin does not hide the files after it" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: az (red)" -- tests/a.test.sh tests/z.test.sh >/dev/null 2>"$T/r9d" </dev/null && [ "$(nr)" = "$b" ] && grep -q "tests/z.test.sh passes" "$T/r9d"'
ln -s missing-target tests/dangling.test.sh
check "red: a symlink whose target is missing is not read as a removal" \
  '! scripts/commit.sh --gate true --red -q -m "test: l (red)" -- tests/dangling.test.sh >/dev/null 2>"$T/r9e"; ! grep -q "is removed" "$T/r9e"'
rm -f tests/dangling.test.sh tests/a.test.sh tests/z.test.sh
printf 'printf "exit 0\\n" > "$0"\nexit 1\n' > tests/s.test.sh
check "red: a test that rewrites itself while it runs commits nothing" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: s (red)" -- tests/s.test.sh >/dev/null 2>"$T/r9f" && [ "$(nr)" = "$b" ] && grep -q "changed while" "$T/r9f"'
rm -f tests/s.test.sh
printf 'red_paths=^tests/|\\.test\\.sh$\nred_run=\\.test\\.sh$\n' > .ant/config
scripts/commit.sh --gate true -q -m "chore: top-level tests" -- .ant/config >/dev/null 2>&1
printf 'exit 0\n' > ./-x.test.sh
check "red: a name that starts with a dash is run as a file, not an option" \
  'b="$(nr)"; ! scripts/commit.sh --gate true --red -q -m "test: d (red)" -- ./-x.test.sh >/dev/null 2>"$T/r9g" && [ "$(nr)" = "$b" ] && grep -q "passes" "$T/r9g"'
cd "$R" || exit 2

# @S-commit-010
# The gate used to come from COMMIT_GATE first: one `export COMMIT_GATE=true`
# and every later commit skipped the gate, with nothing in the command to say so.
R10=$(mkrepo gate10)
cd "$R10" || exit 2
scripts/install-hook.sh >/dev/null 2>&1
mkdir -p .ant; printf 'gate=false\n' > .ant/config
echo g1 > g1
check "--gate names the gate on the command line, in place of gate=" \
  'scripts/commit.sh --gate true -q -m "feat: g1" -- g1 >/dev/null 2>"$T/g1" && git cat-file -e HEAD:g1 || { cat "$T/g1"; false; }'
printf 'gate=true\n' > .ant/config; echo g2 > g2
check "--gate with a red gate commits nothing, though gate= is green" \
  '! scripts/commit.sh --gate false -q -m "feat: g2" -- g2 >/dev/null 2>&1 && ! git cat-file -e HEAD:g2 2>/dev/null'
printf 'gate=touch gate-ran\n' > .ant/config; echo g3 > g3
check "an exported COMMIT_GATE is refused, and no gate runs" \
  '! COMMIT_GATE=true scripts/commit.sh -q -m "feat: g3" -- g3 >/dev/null 2>"$T/g3" && ! git cat-file -e HEAD:g3 2>/dev/null && [ ! -e gate-ran ] && grep -q "COMMIT_GATE is not read -- name the gate with --gate" "$T/g3"'
check "an exported COMMIT_GATE that is empty is refused too" \
  '! COMMIT_GATE= scripts/commit.sh -q -m "feat: g3" -- g3 >/dev/null 2>"$T/g4" && ! git cat-file -e HEAD:g3 2>/dev/null && [ ! -e gate-ran ] && grep -q "COMMIT_GATE is not read" "$T/g4"'

# @S-commit-011
# An uncommitted gate=true replaced the gate on every later commit, unseen in
# the command -- the same shape as COMMIT_GATE, from a file instead.
R11=$(mkrepo gate11)
cd "$R11" || exit 2
scripts/install-hook.sh >/dev/null 2>&1
mkdir -p .ant; printf 'gate=touch gate-ran; false\n' > .ant/config
git add .ant/config; git commit -q --no-verify -m "chore: config"
echo h1 > h1
printf 'gate=true\n' > .ant/config
check "an uncommitted gate= is refused, and no gate runs" \
  '! scripts/commit.sh -q -m "feat: h1" -- h1 >/dev/null 2>"$T/h1" && ! git cat-file -e HEAD:h1 2>/dev/null && [ ! -e gate-ran ] && grep -q "uncommitted gate=" "$T/h1"'
check "with --gate it commits, the config change included" \
  'scripts/commit.sh --gate true -q -m "chore: gate" -- .ant/config h1 >/dev/null 2>"$T/h2" && git cat-file -e HEAD:h1 || { cat "$T/h2"; false; }'
check "the committed gate= is then read as before" \
  'echo h3 > h3 && scripts/commit.sh -q -m "feat: h3" -- h3 >/dev/null 2>&1 && git cat-file -e HEAD:h3'
for k in gate_covered_by=ci gate_env=LD_PRELOAD secret_scan=true secret_scan_found_rc=7; do
  printf 'gate=true\n%s\n' "$k" > .ant/config; echo "$k" > h4
  check "an uncommitted ${k%%=*}= is refused" \
    '! scripts/commit.sh -q -m "feat: h4" -- h4 >/dev/null 2>"$T/h4" && ! git cat-file -e HEAD:h4 2>/dev/null && grep -q "uncommitted ${k%%=*}=" "$T/h4"'
done
for k in gate_env=LD_PRELOAD secret_scan=true; do
  printf 'gate=true\n%s\n' "$k" > .ant/config; echo "$k" > h4
  check "with --gate an uncommitted ${k%%=*}= is still refused" \
    '! scripts/commit.sh --gate true -q -m "feat: h4" -- h4 >/dev/null 2>"$T/h5" && ! git cat-file -e HEAD:h4 2>/dev/null && grep -q "uncommitted ${k%%=*}=.*among the named paths" "$T/h5"'
done
printf 'gate=true\ngate_env=PROBE_X\n' > .ant/config; echo h6 > h6
check "an uncommitted gate_env= commits when .ant/config is named" \
  'scripts/commit.sh -q -m "chore: gate_env" -- .ant/config h6 >/dev/null 2>"$T/h6" && git cat-file -e HEAD:h6 || { cat "$T/h6"; false; }'
printf 'gate=true\nsecret_scan=! grep -q SECRET[X]\n' > .ant/config
scripts/commit.sh --gate true -q -m "chore: scan" -- .ant/config >/dev/null 2>&1
mkdir -p .git/info; printf '* diff=nul\n' > .git/info/attributes; git config diff.nul.textconv true
echo SECRETX > h7
check "a textconv driver does not hide a file from the secret scan" \
  '! scripts/commit.sh -q -m "feat: h7" -- h7 >/dev/null 2>"$T/h7" && ! git cat-file -e HEAD:h7 2>/dev/null && grep -q "found a secret" "$T/h7"'
git config --unset diff.nul.textconv; printf '* -diff\n' > .git/info/attributes
check "a -diff attribute does not hide a file from the secret scan" \
  '! scripts/commit.sh -q -m "feat: h7" -- h7 >/dev/null 2>"$T/h7" && ! git cat-file -e HEAD:h7 2>/dev/null && grep -q "found a secret" "$T/h7"'
rm -f .git/info/attributes
printf 'exit 0\n' > "$T/be0.sh"
check "BASH_ENV does not reach the secret scan" \
  '! BASH_ENV="$T/be0.sh" scripts/commit.sh -q -m "feat: h7" -- h7 >/dev/null 2>&1 && ! git cat-file -e HEAD:h7 2>/dev/null'
check "an exported function does not reach the secret scan" \
  '! bash -c '"'"'grep(){ cat >/dev/null; return 1; }; export -f grep; exec scripts/commit.sh -q -m "feat: h7" -- h7'"'"' >/dev/null 2>&1 && ! git cat-file -e HEAD:h7 2>/dev/null'
rm -f h7
printf 'gate=true\nsecret_scan=grep -q SECRET[X] <<<"$(git cat-file blob "$SECRET_SCAN_REV:h8")" && exit 1; exit 0\n' > .ant/config
scripts/commit.sh --gate true -q -m "chore: blob scan" -- .ant/config >/dev/null 2>&1
echo SECRETX-8 > h8; git replace "$(git hash-object -w h8)" "$(echo clean | git hash-object -w --stdin)"
check "a replace ref does not show the scanner a clean blob" \
  '! scripts/commit.sh -q -m "feat: h8" -- h8 >/dev/null 2>&1 && ! git cat-file -e HEAD:h8 2>/dev/null'
git replace -d "$(git hash-object h8)" >/dev/null; rm -f h8
git show HEAD:.ant/config > .ant/config; printf 'logs_dir=.ant/work/logs\n' >> .ant/config
check "a key that does not choose the gate may differ" \
  'scripts/commit.sh -q -m "feat: h4" -- h4 >/dev/null 2>&1 && git cat-file -e HEAD:h4'
git checkout -q -- .ant/config

# @S-commit-012
# The caller's bash ran first: an exported function or BASH_ENV rewrote
# commit.sh before its first line, and a red gate committed.
printf 'gate=false\n' > .ant/config; git add .ant/config; git commit -q --no-verify -m "chore: red gate"
printf 'echo ran-bash-env >&2\n' > "$T/be.sh"
echo i1 > i1
check "an exported function named sed does not reach commit.sh" \
  '! bash -c '"'"'sed(){ if [ "$2" = "s/^gate=//p" ]; then echo true; else command sed "$@"; fi; }; export -f sed; exec scripts/commit.sh -q -m "feat: i1" -- i1'"'"' >/dev/null 2>&1 && ! git cat-file -e HEAD:i1 2>/dev/null'
check "an exported function named env does not reach commit.sh" \
  '! bash -c '"'"'env(){ true; }; export -f env; exec scripts/commit.sh -q -m "feat: i1" -- i1'"'"' >/dev/null 2>&1 && ! git cat-file -e HEAD:i1 2>/dev/null'
check "BASH_ENV is not read" \
  '! BASH_ENV="$T/be.sh" scripts/commit.sh -q -m "feat: i1" -- i1 >/dev/null 2>"$T/i1" && ! grep -q ran-bash-env "$T/i1"'
check "run as bash scripts/commit.sh, it restarts under bash -p (best effort)" \
  '! bash -c '"'"'env(){ true; }; export -f env; exec bash scripts/commit.sh -q -m "feat: i1" -- i1'"'"' >/dev/null 2>&1 && ! git cat-file -e HEAD:i1 2>/dev/null'
for v in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_EXEC_PATH LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH; do
  check "an exported $v is refused, and no gate runs" \
    '! env "$v=$PWD/.git" scripts/commit.sh --gate "touch gate-ran" -q -m "feat: i1" -- i1 >/dev/null 2>"$T/i2" && [ ! -e gate-ran ] && ! git cat-file -e HEAD:i1 2>/dev/null && grep -q "$v is set" "$T/i2"'
done
cd "$R" || exit 2

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
