#!/usr/bin/env bash
# `release fix VER --record` and the cut: the lead's commits on a release branch are journaled with no plan and no approval, and the record says whether they stay
# inside the paths the cut's plan named (the cut then covers the push) or not (the push takes its own plan, after which the cut goes on from the pushed head);
# release push does the same catch-up and check itself; the paths come from the project's answers; changelog fragments are counted at start and must be folded
# before push and finish. Offline: a bare repository is the origin, gh is a fake. Run: tests/test_release_fix_record.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm QARGI_LEAD=lead GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scr" "$T/bin"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac\n' "$T" > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, approving the cut would be refused as a member's
REL="$DA release"
J=$T/s/ref-journal.jsonl
mk() { # NAME [ANSWERS-JQ]: a repository with origin, master and develop, a version file, a changelog, code, docs and a manual page; the project's answers; the suite recorded as passed
  R=$T/$1; O=$T/$1-origin.git; mkdir -p "$R/src" "$R/docs" "$R/man" "$R/pkg"; git init -q -b master "$R"; git init -q --bare "$O"
  echo 0.1.0 > "$R/VERSION"; echo 0.1.0 > "$R/pkg/version.txt"; echo code > "$R/src/code.go"; echo guide > "$R/docs/guide.md"
  printf '.TH APP 1 "2026-01-01" "app 0.1.0"\n.SH NAME\napp\n' > "$R/man/app.1"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one
  [ -z "${PRE:-}" ] || { (cd "$R" && eval "$PRE") && git -C "$R" add -A && git -C "$R" commit -q -m "the base of the test"; }   # PRE: shell text that changes the base before develop is made
  git -C "$R" branch develop && git -C "$R" remote add origin "$O" && git -C "$R" push -q origin master develop
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  [ -z "${2:-}" ] || { jq "$2" "$T/c/projects/$1.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/$1.json"; }
  export QARGI_PROJECT=$1 CR=$T/s/release/$1-0.2.0.cut.json
  $REL verify 0.2.0 >/dev/null 2>&1
}
cutup() { # NAME [ANSWERS-JQ]: mk, then the plan of the cut, its approval and its start step: CT is the cut's token
  mk "$@"; local out
  PLANOUT=$($REL plan 0.2.0 --date 2026-03-04 2>&1); out=$PLANOUT; CT=$(tok <<<"$out")
  $REL plan 0.2.0 --date 2026-03-04 --plan "$CT" --approved "ship it" >/dev/null 2>&1 && $REL start 0.2.0 --plan "$CT" >/dev/null 2>&1 || no "(setup) the cut of $1 did not start: $out"
  W=$($REL fix 0.2.0 | sed -n 's/^worktree: //p')
}
cm() { # FILE TEXT MESSAGE: a commit in the fix worktree, by hand
  mkdir -p "$W/$(dirname "$1")"; printf '%s\n' "$2" >> "$W/$1"; git -C "$W" add -A && git -C "$W" commit -q -m "$3"
}
head_of() { git -C "$R" rev-parse "refs/heads/$1"; }
cutget() { jq -r "$1" "$CR"; }
jhas() { [ -f "$J" ] && jq -Rc --arg r "$1" --arg o "$2" --arg n "$3" 'fromjson? | select((.ref | endswith($r)) and .old == $o and .new == $n)' "$J" | grep -q .; }
mkrun() { $DA local prepare --repo "$R" --base develop --slug "$1" --scratch "$T/scr" | sed -n 's/^RUN=//p'; }
leftover() { find "$T/s" -maxdepth 1 -name '.release-*'; }   # what a verb left in the state directory: its scratch files are removed on every exit
snap() { { git -C "$R" for-each-ref; git -C "$R" worktree list --porcelain; [ ! -f "$J" ] || cat "$J"; cat "$T/s/release/"*.cut.json "$T/s/audit.log" 2>/dev/null; } | md5sum; }

# --- a fix that stays inside the paths of the cut: --record journals it with no plan and no approval, says it is inside, and push goes on under the cut
cutup c1
RA=$(mkrun ra); [ -n "$RA" ] || no "(setup) run: $RA"
cm CHANGELOG.md "- a fixed thing" "fold a note"
h1=$(head_of release/0.2.0); s0=$(cutget '.done.start.head')
out=$($DA local verify "$RA" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -qi journal <<<"$out" && ok "before --record: a commit made with git on the release branch is not explained by the journal, so a run prepared earlier is refused" || no "verify before record: rc=$rc $out"
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "journaled 1 commit made with git on release/0.2.0" <<<"$out" && grep -q "inside the cut: 1 commit since ${s0:0:7} change only the paths the cut's plan named: push goes on under its approval" <<<"$out" \
  && [ "$(cutget '.done.fix.head')" = "$h1" ] && [ "$(cutget '.done.fix.via')" = own ] && jhas release/0.2.0 "$s0" "$h1" \
  && ok "--record with no plan, no token and no --approved exits 0, journals the commit, says it is inside the cut and records fix at that head" || no "record: rc=$rc $out; $(cat "$CR")"
out=$($DA local verify "$RA" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a run prepared before the fix commit verifies once the fix is recorded" || no "verify after record: rc=$rc $out"
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "already leads to" <<<"$out" && grep -q "where the cut $CT left it" <<<"$out" && ok "--record again changes nothing and says so" || no "record again: rc=$rc $out"
out=$($REL plan 0.2.0 2>&1); grep -q "^  fix recorded .* at ${h1:0:7} (inside the cut's paths)" <<<"$out" && ok "the report of the cut shows the recorded fix" || no "cut report: $out"
out=$($REL push 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$O" rev-parse refs/heads/release/0.2.0)" = "$h1" ] && [ "$(cutget '.done.push.head')" = "$h1" ] && [ "$(cutget '.done.push.via')" = cut ] && [ "$(cutget '.done.push.seq')" -gt "$(cutget '.done.fix.seq')" ] \
  && ok "push --plan CUT passes after the recorded fix: the branch is pushed, push is recorded after fix, and the cut's words are the push's" || no "push after record: rc=$rc $out"

# --- --record with no cut journals and says nothing of a cut
mk c2
$REL plan 0.2.0 >/dev/null 2>&1; t=$($REL start 0.2.0 | tok); $REL start 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
W=$($REL fix 0.2.0 | sed -n 's/^worktree: //p'); RB=$(mkrun rb)
s0=$(head_of release/0.2.0); cm src/code.go "changed" "a code fix"; h1=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "journaled 1 commit" <<<"$out" && ! grep -qiE "inside the cut|outside the cut|cut-fix-outside|the cut record" <<<"$out" && jhas release/0.2.0 "$s0" "$h1" && ! ls "$T/s/release/"*c2* >/dev/null 2>&1 && ok "--record with no cut journals the commit and says nothing of a cut" || no "record without a cut: rc=$rc $out"
$DA local verify "$RB" >/dev/null 2>&1 && ok "and a run prepared before verifies" || no "verify, no cut: $($DA local verify "$RB" 2>&1)"
out=$($REL fix 0.2.0 --record --plan x 2>&1); rc=$?
[ "$rc" = 2 ] && ok "--record takes neither --plan nor --approved" || no "record with a plan: rc=$rc $out"
out=$($REL fix 0.2.0 --record --push 2>&1); rc=$?
[ "$rc" = 2 ] && ok "--record and --push are not combined" || no "record and push: rc=$rc $out"
out=$($REL status 0.2.0 --record 2>&1); [ "$?" = 2 ] && ok "--record belongs to release fix" || no "--record on status: $out"
mkdir -p "$T/memberrun"; : > "$T/memberrun/ability"; : > "$T/memberrun/refs.before"
out=$(cd "$T/memberrun" && $REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "is not available in a member run" <<<"$out" && ok "--record is refused in a member run (it is the lead's)" || no "record in a member run: rc=$rc $out"

# --- push under the cut with no --record before it gives the same result as with it
cutup c3
RC=$(mkrun rc); cm CHANGELOG.md "- another" "fold"; h1=$(head_of release/0.2.0); s0=$(cutget '.done.start.head')
out=$($REL push 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(cutget '.done.fix.head')" = "$h1" ] && [ "$(cutget '.done.push.head')" = "$h1" ] && jhas release/0.2.0 "$s0" "$h1" && ok "push under the cut with no --record: the same catch-up and check, fix and push are recorded, the journal has the step" || no "push without record: rc=$rc $out; $(cat "$CR")"
$DA local verify "$RC" >/dev/null 2>&1 && ok "and a run prepared before the fix verifies" || no "verify after push: $($DA local verify "$RC" 2>&1)"

# --- the sequence: a fold (inside), a code fix (outside), a text touch-up (inside)
cutup c4
s0=$(cutget '.done.start.head'); RD=$(mkrun rd)
cm CHANGELOG.md "- folded" "fold the notes"; a1=$(head_of release/0.2.0)
cm src/code.go "fixed" "fix the code"; a2=$(head_of release/0.2.0)
cm CHANGELOG.md "- touched up" "touch up the text"; a3=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "journaled 3 commits" <<<"$out" && jhas release/0.2.0 "$s0" "$a1" && jhas release/0.2.0 "$a1" "$a2" && jhas release/0.2.0 "$a2" "$a3" && [ "$(cutget '.done | has("fix")')" = false ] \
  && grep -q "outside the cut: push will take its own plan" <<<"$out" && grep -q "qargi: note \[cut-fix-outside\] the commits ${a2:0:7} leave the paths the cut covers" <<<"$out" && ! grep -q "${a1:0:7} leave\|${a3:0:7} leave" <<<"$out" \
  && ok "--record journals all three commits, exits 0, names the code commit only as outside, and records no fix in the cut" || no "record, mixed: rc=$rc $out; $(cat "$CR")"
$DA local verify "$RD" >/dev/null 2>&1 && ok "the run prepared before the three commits verifies" || no "verify, mixed: $($DA local verify "$RD" 2>&1)"
before=$(snap); out=$($REL push 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '^qargi-refusal/1 {"code":"cut-fix-outside","exit":1,"verb":"release push"' <<<"$out" && grep -q "detail\":\"commits=${a2:0:7}\"" <<<"$out" && grep -q "refused \[cut-fix-outside\] the commits ${a2:0:7} leave" <<<"$out" \
  && grep -q "next: run qargi release push VER without the cut's token" <<<"$out" && [ -z "$(git -C "$O" for-each-ref refs/heads/release/0.2.0)" ] && [ "$before" = "$(snap)" ] \
  && ok "push --plan CUT is refused with cut-fix-outside and the same list; nothing was pushed, recorded or journaled" || no "push under the cut, outside: rc=$rc $out"
out=$($REL push 0.2.0 2>&1); t=$(tok <<<"$out")
grep -q "commits on release/0.2.0 since the cut $CT last stood at ${s0:0:7}: 3" <<<"$out" && grep -q "outside the cut's paths: ${a2:0:7}" <<<"$out" && ok "the own plan of push lists every commit since the cut's anchor and says which are outside" || no "own plan: $out"
out=$($REL push 0.2.0 --plan "$t" --approved "pushing the code fix" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$O" rev-parse refs/heads/release/0.2.0)" = "$a3" ] && [ "$(cutget '.done.push.own_plan')" = "$t" ] && [ "$(cutget '.done.push.head')" = "$a3" ] && [ "$(cutget '.done.push.via')" = own ] \
  && [ "$(cutget '.done | has("finish")')" = false ] && [ "$(cutget '.token')" = "$CT" ] && ok "push by its own plan and approval passes; the cut stays live, anchored at the pushed head, and records the plan's token" || no "own push: rc=$rc $out; $(cat "$CR")"
cm CHANGELOG.md "- one more touch-up" "touch up again"; a4=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "inside the cut: 1 commit since ${a3:0:7}" <<<"$out" && [ "$(cutget '.done.fix.head')" = "$a4" ] && ok "after the re-anchor a confined fix is counted from the pushed head: inside, fix recorded" || no "record after re-anchor: rc=$rc $out; $(cat "$CR")"
out=$($REL push 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$O" rev-parse refs/heads/release/0.2.0)" = "$a4" ] && [ "$(cutget '.done.push.head')" = "$a4" ] && [ "$(cutget '.done.push.via')" = cut ] && ok "and push under the cut passes again" || no "push after re-anchor: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "finish under the cut goes on from the pushed head" || no "finish: rc=$rc $out"

# --- the paths come from the project's answers: the changelog fragments directory, CHANGELOG.md, the version file and release.version_files; docs/ and a manual page are outside
cutup c5 '.release = {changelog: {fragments: "changelog.d"}, version_files: ["pkg/version.txt"]}'
[ "$(cutget '.fix_paths | join(" ")')" = "changelog.d CHANGELOG.md VERSION pkg/version.txt" ] && ok ".fix_paths are the fragments directory, CHANGELOG.md, the version file and the version_files of the answers, in the cut record" || no "fix_paths: $(cutget '.fix_paths')"
grep -q "a fix that changes only these paths goes on under this approval: changelog.d CHANGELOG.md VERSION pkg/version.txt (docs/ and the manual pages are outside" <<<"$PLANOUT" && ok "the plan prints them" || no "plan text: $PLANOUT"
cm pkg/version.txt "0.2.0" "version file"; cm changelog.d/x.md "- frag" "fragment"; cm CHANGELOG.md "- n" "changelog"
out=$($REL fix 0.2.0 --record 2>&1); grep -q "inside the cut: 3 commits" <<<"$out" && ok "a version file, a fragment and the changelog are inside" || no "inside: $out"
cm docs/guide.md "more" "docs"; d1=$(head_of release/0.2.0); cm man/app.1 ".SH MORE" "manual page"; d2=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1)
grep -q "the commits ${d1:0:7},${d2:0:7} leave the paths" <<<"$out" || grep -q "the commits ${d1:0:7}, ${d2:0:7} leave the paths" <<<"$out" && ok "a commit in docs/ and a commit on a manual page are outside" || no "docs and manual: $out"
cutup c6 '.release = {changelog: {fragments: "changelog.d"}}'
mkdir -p "$W/changelog.d"; git -C "$W" mv docs/guide.md changelog.d/guide.md; git -C "$W" commit -q -m "rename into the fragments directory"; r1=$(head_of release/0.2.0)
git -C "$W" mv CHANGELOG.md docs/CHANGELOG.md; git -C "$W" commit -q -m "rename the changelog into docs"; r2=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1)
grep -q "the commits ${r1:0:7},${r2:0:7} leave the paths\|the commits ${r1:0:7}, ${r2:0:7} leave the paths" <<<"$out" && ok "a rename counts on both sides: out of docs/ into the fragments directory, and out of the changelog into docs/, are both outside" || no "renames: $out"

# --- changelog fragments (release.changelog.fragments): they count as notes at start, and push and finish refuse while one is left at the branch head or the released section is empty
FRAG='.release = {changelog: {fragments: "changelog.d"}}'
EMPTYCL="printf '# Changelog\n\n## [Unreleased]\n\n' > CHANGELOG.md; mkdir changelog.d; echo '- a fragment' > changelog.d/a.md; echo readme > changelog.d/README.md; : > changelog.d/.gitkeep"
PRE=$EMPTYCL mk f1 "$FRAG"; PRE=''
out=$($REL start 0.2.0 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "changelog fragments (release.changelog.fragments: changelog.d): 1 fragment, to be folded on the branch" <<<"$out" && ok "start with the answer: an empty unreleased section is fine when a fragment stands in for notes (README and .gitkeep are not fragments); the plan says 1 fragment, to be folded on the branch" || no "fragment plan: rc=$rc $out"
t=$(tok <<<"$out"); out=$($REL start 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "and the start is applied with no --allow-empty-notes" || no "fragment start: rc=$rc $out"
before=$(snap); out=$($REL push 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '^qargi-refusal/1 {"code":"release-fragments-unfolded","exit":1,"verb":"release push"' <<<"$out" && grep -q 'detail":"count=1"' <<<"$out" && grep -q "next: fold them in the fix worktree, commit, then run qargi release fix VER --record" <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ "$before" = "$(snap)" ] \
  && ok "push refuses while a fragment is at the branch head: release-fragments-unfolded, count 1, no plan token, nothing changed" || no "push with a fragment: rc=$rc $out"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded","exit":1,"verb":"release finish"' <<<"$out" && [ -z "$(leftover)" ] && ok "finish refuses too, and leaves nothing in the state directory" || no "finish with a fragment: rc=$rc $out"
W=$($REL fix 0.2.0 | sed -n 's/^worktree: //p')
git -C "$W" rm -q changelog.d/a.md && git -C "$W" commit -q -m "remove the fragment, forgetting the note"
out=$($REL push 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded"' <<<"$out" && grep -q "has no notes" <<<"$out" && ok "with no fragment left and an empty released section push still refuses: the note was not folded" || no "empty released section: rc=$rc $out"
printf -- '- a fragment\n' >> "$W/CHANGELOG.md"; git -C "$W" commit -q -am "fold the fragment"
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "journaled 2 commits" <<<"$out" && ok "the fold is recorded" || no "record the fold: rc=$rc $out"
out=$($REL push 0.2.0 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q '^plan token:' <<<"$out" && ok "once the fragment is folded (only README and .gitkeep remain) push shows its plan" || no "push after the fold: rc=$rc $out"
t=$(tok <<<"$out"); out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && out=$($REL finish 0.2.0 2>&1) && grep -q '^plan token:' <<<"$out" && ok "and so does finish" || no "push or finish after the fold: rc=$rc $out"

PRE=$EMPTYCL mk f2; PRE=''
out=$($REL start 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '^qargi-refusal/1 {"code":"release-notes-empty","exit":1,"verb":"release start"' <<<"$out" && grep -q "next: write the notes, pass --allow-empty-notes, or set the answer release.changelog.fragments" <<<"$out" && grep -q "more: CHANGELOG.md has nothing under '## \[Unreleased\]'" <<<"$out" \
  && ok "without the answer an empty unreleased section is release-notes-empty, and the next step names the option and the answer" || no "notes empty: rc=$rc $out"
out=$($REL start 0.2.0 --allow-empty-notes 2>&1); [ "$?" = 0 ] && grep -q '^plan token:' <<<"$out" && ok "--allow-empty-notes still waives it" || no "allow empty: $out"
PRE="printf '# Changelog\n\n## [Unreleased]\n\n' > CHANGELOG.md; mkdir changelog.d; : > changelog.d/.gitkeep" mk f3 "$FRAG"
out=$($REL start 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-notes-empty"' <<<"$out" && ok "with the answer but no fragment (only .gitkeep) and an empty unreleased section the notes are still empty" || no "answer without fragments: rc=$rc $out"

# a branch that deletes its fragments together with the released section, or with the changelog, folded nothing: push and finish refuse
PRE=$EMPTYCL mk f5 "$FRAG"; PRE=''
t=$($REL start 0.2.0 | tok); $REL start 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
W=$($REL fix 0.2.0 | sed -n 's/^worktree: //p')
git -C "$W" rm -q changelog.d/a.md && printf '# Changelog\n\n## [Unreleased]\n\n' > "$W/CHANGELOG.md" && git -C "$W" commit -q -am "delete the fragment and the section of the version"
before=$(snap); out=$($REL push 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded","exit":1,"verb":"release push"' <<<"$out" && grep -q "has no released section for 0.2.0" <<<"$out" && ! grep -q '^plan token' <<<"$out" && [ "$before" = "$(snap)" ] \
  && ok "push refuses a branch whose changelog has no section of the version (its fragments deleted with it), naming the missing section" || no "push, no section: rc=$rc $out"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded","exit":1,"verb":"release finish"' <<<"$out" && grep -q "has no released section for 0.2.0" <<<"$out" && [ -z "$(leftover)" ] && ok "and finish refuses it, leaving nothing in the state directory" || no "finish, no section: rc=$rc $out"
git -C "$W" rm -q CHANGELOG.md && git -C "$W" commit -q -m "delete the changelog"
out=$($REL push 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded","exit":1,"verb":"release push"' <<<"$out" && grep -q "has no CHANGELOG.md" <<<"$out" && ok "push refuses a branch with no CHANGELOG.md at the head" || no "push, no changelog: rc=$rc $out"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"release-fragments-unfolded","exit":1,"verb":"release finish"' <<<"$out" && grep -q "has no CHANGELOG.md" <<<"$out" && ok "and finish refuses it" || no "finish, no changelog: rc=$rc $out"

# --- a dry run lists independent refusals: an unfolded fragment and a commit outside the cut's paths
PRE=$EMPTYCL cutup f4 "$FRAG"; PRE=''
cm src/code.go "changed" "a code fix"
before=$(snap); $REL fix 0.2.0 --push --dry-run --plan "$CT" >"$T/do" 2>"$T/de"; rc=$?
[ "$rc" = 1 ] && [ "$(tail -n 1 "$T/do")" = "dry-run: 2 would refuse; nothing was changed" ] && grep -q '^qargi-refusal/1 {"code":"release-fragments-unfolded","exit":1,"verb":"release push".*"detail":"dry=1 count=1"' "$T/de" && grep -q '^qargi-refusal/1 {"code":"cut-fix-outside","exit":1,"verb":"release push".*"detail":"dry=1 commits=' "$T/de" && [ "$before" = "$(snap)" ] && [ -z "$(leftover)" ] \
  && ok "fix --push --dry-run lists both an unfolded fragment and a commit outside the cut's paths: 2 would refuse, nothing changed" || no "independent refusals: rc=$rc $(cat "$T/do" "$T/de")"

# --- what is judged is what the commits contain, not what the configuration shows: a gitlink is a change of a path even when diff.ignoreSubmodules hides it, and a replace ref changes nothing
cutup c7
git -C "$R" config diff.ignoreSubmodules all
git -C "$W" update-index --add --cacheinfo "160000,$(head_of master),sub" && git -C "$W" commit -q -m "add a gitlink"; g1=$(head_of release/0.2.0)
[ -z "$(git -C "$R" diff --name-only "$g1^" "$g1")" ] && ok "(setup) with diff.ignoreSubmodules=all the porcelain diff does not list the gitlink" || no "(setup) the porcelain diff lists the gitlink: $(git -C "$R" diff --name-only "$g1^" "$g1")"
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "outside the cut: push will take its own plan" <<<"$out" && grep -q "the commits ${g1:0:7} leave the paths" <<<"$out" && [ "$(cutget '.done | has("fix")')" = false ] \
  && ok "a commit that only adds a gitlink is outside the cut with diff.ignoreSubmodules=all: cut-fix-outside, no fix recorded" || no "gitlink: rc=$rc $out; $(cat "$CR")"
out=$($REL push 0.2.0 --plan "$CT" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q '"code":"cut-fix-outside"' <<<"$out" && [ -z "$(git -C "$O" for-each-ref refs/heads/release/0.2.0)" ] && ok "and push under the cut is refused: nothing was pushed" || no "push after a gitlink: rc=$rc $out"
cutup c8
cm src/code.go "replaced" "a code fix that a replace ref hides"; p1=$(head_of release/0.2.0)
rp=$(git -C "$R" commit-tree "$(git -C "$R" rev-parse "$p1^^{tree}")" -p "$(git -C "$R" rev-parse "$p1^")" -m "the same tree as its parent")
git -C "$R" replace "$p1" "$rp"
out=$($REL fix 0.2.0 --record 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "outside the cut: push will take its own plan" <<<"$out" && grep -q "the commits ${p1:0:7} leave the paths" <<<"$out" && [ "$(cutget '.done | has("fix")')" = false ] \
  && ok "a refs/replace entry that makes a code commit look empty does not change what is judged" || no "replace: rc=$rc $out; $(cat "$CR")"

# --- a path entry of the cut is a whole name (a directory only for the fragments directory), and an entry is judged by its kind: a symlink, a gitlink or a mode change is outside
cutup c9 '.release = {changelog: {fragments: "changelog.d"}}'
[ "$(cutget '.fix_dirs | join(" ")')" = "changelog.d" ] && ok "the cut record names the fragments directory as the one prefix entry (.fix_dirs)" || no "fix_dirs: $(cutget '.fix_dirs')"
git -C "$W" rm -q VERSION && mkdir "$W/VERSION" && echo x > "$W/VERSION/x" && git -C "$W" add -A && git -C "$W" commit -q -m "VERSION becomes a directory"; l1=$(head_of release/0.2.0)
git -C "$W" rm -q CHANGELOG.md && mkdir "$W/CHANGELOG.md" && echo x > "$W/CHANGELOG.md/build.sh" && git -C "$W" add -A && git -C "$W" commit -q -m "CHANGELOG.md becomes a directory"; l2=$(head_of release/0.2.0)
mkdir -p "$W/changelog.d" && ln -s ../src/code.go "$W/changelog.d/link.md" && git -C "$W" add -A && git -C "$W" commit -q -m "a symlink in the fragments directory"; l3=$(head_of release/0.2.0)
cm changelog.d/ok.md "- a note" "a fragment"; l4=$(head_of release/0.2.0)
git -C "$W" update-index --add --cacheinfo "160000,$(head_of master),changelog.d/sub" && git -C "$W" commit -q -m "a gitlink in the fragments directory"; l5=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1)
grep -q "of these commits; ${l1:0:7} ${l2:0:7} ${l3:0:7} ${l5:0:7} change a path" <<<"$out" && ! grep -q "${l4:0:7}" <<<"$out" \
  && ok "VERSION/x and CHANGELOG.md/build.sh are not the files VERSION and CHANGELOG.md, a symlink and a gitlink in the fragments directory are not fragments: all outside; the fragment between them is inside" || no "whole names and kinds: $out"
cutup c10
chmod +x "$W/CHANGELOG.md" && git -C "$W" add -A && git -C "$W" commit -q -m "make the changelog executable"; m1=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1)
grep -q "of these commits; ${m1:0:7} change a path" <<<"$out" && ok "a mode change of a named file is outside" || no "mode change: $out"
cutup c11
rm "$W/VERSION" && ln -s CHANGELOG.md "$W/VERSION" && git -C "$W" add -A && git -C "$W" commit -q -m "VERSION becomes a symlink"; m2=$(head_of release/0.2.0)
out=$($REL fix 0.2.0 --record 2>&1)
grep -q "of these commits; ${m2:0:7} change a path" <<<"$out" && ok "a named file that becomes a symlink is outside" || no "symlink: $out"
# the filter itself, on crafted raw entries (name, old and new mode)
RLP=${DA%/bin/qargi}/lib/release_layout.py
RAWF() { printf ':%s %s 0000000000000000000000000000000000000000 1111111111111111111111111111111111111111 M\0%s\0' "$1" "$2" "$3"; }
out=$(RAWF 100644 100644 changelog.d/a.md | python3 -I "$RLP" outside --dir changelog.d CHANGELOG.md); rc=$?
[ "$rc" = 0 ] && [ -z "$out" ] && ok "the filter: a file under the directory is inside" || no "filter inside: rc=$rc $out"
out=$(RAWF 100644 100644 changelog.d | python3 -I "$RLP" outside --dir changelog.d CHANGELOG.md); rc=$?
[ "$rc" = 1 ] && [ "$out" = changelog.d ] && ok "the filter: a file named as the directory is not under it" || no "filter dir name: rc=$rc $out"
out=$({ RAWF 100644 100644 CHANGELOG.md; RAWF 100644 100755 VERSION; RAWF 000000 120000 CHANGELOG.md/x; RAWF 160000 000000 CHANGELOG.md; } | python3 -I "$RLP" outside CHANGELOG.md VERSION); rc=$?
[ "$rc" = 1 ] && [ "$out" = "$(printf 'VERSION\nCHANGELOG.md/x\nCHANGELOG.md')" ] && ok "the filter: a mode change, a name that only starts with an entry, and a gitlink are outside; a plain edit of an entry is inside" || no "filter matrix: rc=$rc $out"
out=$({ RAWF 000000 100644 VERSION; RAWF 100755 000000 VERSION; } | python3 -I "$RLP" outside VERSION); rc=$?
[ "$rc" = 0 ] && ok "the filter: an added or deleted regular file is inside" || no "filter add/delete: rc=$rc $out"

exit $fail
