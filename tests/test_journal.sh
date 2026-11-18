#!/usr/bin/env bash
# The ref-move journal ($QARGI_STATE/ref-journal.jsonl): every local branch creation, move and deletion made by qargi's
# own verbs is recorded, so `qargi local verify` can accept what the lead did since a run's snapshot and still refuse
# anything done by hand, any tag, and any push. Run: tests/test_journal.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export QARGI_LEAD=lead HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm QARGI_PROJECT=app
export GIT_AUTHOR_NAME=lead GIT_AUTHOR_EMAIL=lead@example.net GIT_COMMITTER_NAME=lead GIT_COMMITTER_EMAIL=lead@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scr" "$T/bin"
J=$T/s/ref-journal.jsonl; Z=0000000000000000000000000000000000000000
# a fake gh (the release finish asks for CI and opens pull requests)
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
chmod +x "$T/bin/gh"; export PATH=$T/bin:$PATH
A=$T/app; git init -q -b master "$A"; git init -q --bare "$T/origin.git"
mkdir -p "$A/internal"; echo 0.1.0 > "$A/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$A/CHANGELOG.md"; echo a > "$A/internal/a.go"
git -C "$A" add -A && git -C "$A" commit -q -m base && git -C "$A" branch develop && git -C "$A" remote add origin "$T/origin.git" && git -C "$A" push -q origin master develop
git -C "$A" checkout -q -b parked   # the main checkout is on neither long-lived branch
jq -n --arg p "$A" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"; REL="$DA release"
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
sha() { git -C "$A" rev-parse -q --verify "$1" 2>/dev/null || echo "$Z"; }
jn() { if [ -f "$J" ]; then wc -l < "$J"; else echo 0; fi; }
# jhas REF-SUFFIX OLD NEW: the journal holds a line for that ref (a branch name ending as given) going from OLD to NEW (a line that is not JSON is
# skipped, as the readers of qargi skip it: a test puts one in the journal)
jhas() { [ -f "$J" ] && jq -Rc --arg r "$1" --arg o "$2" --arg n "$3" 'fromjson? | select((.ref | endswith($r)) and .old == $o and .new == $n)' "$J" | grep -q .; }
mkrun() { $DA local prepare --repo "$A" --base "${2:-develop}" --slug "$1" --scratch "$T/scr" | sed -n 's/^RUN=//p'; }
verify() { $DA local verify "$1" 2>&1; }
# a hand-made commit on top of a branch (nothing moves)
hand() { git -C "$A" commit-tree -p "$1" -m "by hand" "$1^{tree}"; }
mk() { GIT_AUTHOR_DATE="2026-10-27T10:00:00" GIT_COMMITTER_DATE="2026-10-27T10:00:00" git commit -q -m "$1" -m "$2"; }
manifest() { # dir: a manifest for the commits BASE..HEAD of the current directory
  git log --reverse --format='%H%x09%s' "$BASE..HEAD" | jq -R -s -c '
    [split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})),
       patch_groups:[{name:"g", why:"one change", commits:($c|map(.sha))}]}' > "$1/manifest.json"; }
seriesrun() { # slug file base -> RUN prepared on base, with a one-commit series returned in out/
  local r c
  r=$(mkrun "$1" "$3") || return 1; c=$r/clone
  ( cd "$c" || exit 1; BASE=$(git rev-parse HEAD); echo "$1" >> "internal/$2"; git add -A
    mk "names: change $2" "The $2 file changes, as the $1 task asks."
    mkdir -p "$r/out/patches"; git format-patch -q -o "$r/out/patches" "$BASE..HEAD"; manifest "$r/out"; echo "# series" > "$r/out/series.md" )
  echo "$r"
}
task() { # branch file text: a task branch of one commit cut from develop (as an applied, verified series would be)
  local w; git -C "$A" branch "$1" develop; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q "$w" "$1"
  echo "$3" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$A" worktree remove --force "$w"
}
# refused RUN NAME: verify exits non-zero and names the journal
refused() { local out rc; out=$(verify "$1"); rc=$?; if [ $rc != 0 ] && grep -qi journal <<<"$out"; then ok "verify refuses $2 and names the journal"; else no "$2: rc=$rc $out"; fi; }
# tamper JQ: rewrite the last journal line with a jq filter
tamper() { local last; last=$(tail -n 1 "$J"); head -n -1 "$J" > "$J.new"; jq -c "$1" <<<"$last" >> "$J.new"; mv "$J.new" "$J"; }

# --- the problem: two runs on one base, the first merged by the lead, the second must still verify
$F start fa >/dev/null 2>&1
f0=$(sha feature/fa)
jhas feature/fa "$Z" "$f0" && ok "feature start journals the creation (old is all zeros)" || no "feature start left no journal line: $(cat "$J" 2>&1)"
RA=$(seriesrun a a2.go feature/fa); RB=$(seriesrun b b2.go feature/fa)
[ -n "$RA" ] && [ -n "$RB" ] && [ "$(git -C "$A" rev-parse feature/fa)" = "$f0" ] && ok "(setup) two runs A and B are prepared on feature/fa, each with a one-commit series" || no "setup runs: A=$RA B=$RB"
$DA local verify "$RA" >/dev/null 2>&1 && ok "verify A passes before anything is applied" || no "verify A: $(verify "$RA")"
out=$($DA review apply "$RA" 2>&1) || no "review apply A: $out"
a0=$(sha agent/a)
[ "$a0" != "$Z" ] && jhas agent/a "$Z" "$a0" && ok "review apply journals the new task branch" || no "review apply left no journal line for agent/a"
$F merge fa agent/a >/dev/null 2>&1 || no "merge: $($F merge fa agent/a 2>&1)"
f1=$(sha feature/fa)
jhas feature/fa "$f0" "$f1" && [ "$f1" != "$f0" ] && ok "feature merge journals the move of the feature branch" || no "feature merge left no journal line"
[ ! -f "$RB/verified" ] || no "(setup) B was verified already"
out=$(verify "$RB"); rc=$?
[ $rc = 0 ] && [ -f "$RB/verified" ] && ok "verify B passes after A was applied and merged: every ref change since its snapshot is journaled" || no "verify B: rc=$rc $out"
$DA review apply "$RB" >/dev/null 2>&1 && $F merge fa agent/b >/dev/null 2>&1 && $DA local verify "$RB" >/dev/null 2>&1 && ok "and B itself can then be applied and merged, and still verifies" || no "B after A: $(verify "$RB")"

# the journal's shape: one JSON line per move with every field
bad=$(jq -c 'select((keys - ["why"] | sort) != ["at","by","epoch","new","old","project","ref","repo","verb"] or (.old|test("^[0-9a-f]{40}$")|not) or (.new|test("^[0-9a-f]{40}$")|not) or (.epoch|type) != "number" or .project != "app" or (.by|length) == 0 or (.verb|length) == 0)' "$J" 2>&1 | head -3)
[ -f "$J" ] && [ -z "$bad" ] && ok "every journal line has at, epoch, verb, project, repo, ref, old, new and by" || no "journal lines: $bad"
[ "$(jq -r '.repo' "$J" | sort -u | wc -l)" = 1 ] && ok "every line names the same repository" || no "repo field"
jq -e 'select(.verb | test("merge"))' "$J" >/dev/null && ok "the verb of a merge says so" || no "verb"

# --- a refused or failed operation journals nothing
n=$(jn)
$F merge fa agent/nosuch >/dev/null 2>&1 && no "a merge of a branch that does not exist worked" || ok "merging a branch that does not exist is refused"
$F start master >/dev/null 2>&1; $F start fa >/dev/null 2>&1
$F merge fa agent/a >/dev/null 2>&1   # already in the feature
[ -f "$J" ] && [ "$(jn)" = "$n" ] && ok "refusals (no branch, a long-lived name, an existing feature, a branch already merged) add no journal line" || no "refusals journaled: $(tail -n +"$((n + 1))" "$J")"
$F start cc >/dev/null 2>&1; task agent/x1 clash.txt one; task agent/x2 clash.txt two
$F merge cc agent/x1 >/dev/null 2>&1
n=$(jn); c1=$(sha feature/cc)
$F merge cc agent/x2 >/dev/null 2>&1; rc=$?
[ $rc != 0 ] && [ "$(sha feature/cc)" = "$c1" ] && [ -f "$J" ] && [ "$(jn)" = "$n" ] && ok "a conflicting merge fails, moves nothing and adds no journal line" || no "conflict: rc=$rc lines $n -> $(jn)"
rm -rf "$T/s/conflicts"

# --- sync journals the feature's move
$F start sy >/dev/null 2>&1
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q --detach "$w" develop; echo late > "$w/late.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "develop moves on"
git -C "$A" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$A" worktree remove --force "$w"
RS=$(mkrun sync-run); s0=$(sha feature/sy)
$F sync sy >/dev/null 2>&1 || no "sync: $($F sync S 2>&1)"
s1=$(sha feature/sy)
jhas feature/sy "$s0" "$s1" && [ "$s1" != "$s0" ] && ok "feature sync journals the move" || no "feature sync left no journal line"
out=$(verify "$RS"); [ $? = 0 ] && ok "a run prepared before the sync verifies" || no "verify after sync: $out"

# --- branch prune journals the deletions (agent/a and agent/b were merged into the open feature/fa above)
RP=$(mkrun prune-run); n=$(jn); b0=$(sha agent/b)
pout=$($DA branch prune 2>&1); pt=$(tok <<<"$pout")
[ -n "$pt" ] && [ -f "$J" ] && [ "$(jn)" = "$n" ] && ok "a branch prune plan (a listing) journals nothing" || no "prune plan journaled or has no token: $pout"
grep -q "delete local agent/a " <<<"$pout" && ! grep -q "journal: takes" <<<"$pout" && ! grep -q "journal: .* agent/[ab]:" <<<"$pout" && grep -q "journal: no step will be journaled for agent/x1:" <<<"$pout" \
  && ok "and it names no commit made with git: the branches it deletes have none the journal lacks (agent/a and agent/b have their lines; agent/x1, made by hand and never noted, has the line that says no step will be journaled for it)" || no "prune plan names commits made with git: $pout"
pout=$($DA branch prune --plan "$pt" --approved "prune them" 2>&1); dels=$(grep -c '^deleted ' <<<"$pout")
jhas agent/a "$a0" "$Z" && jhas agent/b "$b0" "$Z" && [ "$(jn)" -ge $((n + 2)) ] && ok "branch prune journals each deletion (new is all zeros)" || no "prune left no journal lines: $pout"
[ "$(jq -c 'select(.new == "0000000000000000000000000000000000000000")' "$J" | tail -n "$dels" | wc -l)" = "$dels" ] && ok "one deletion line per deleted branch" || no "deletion lines vs '$pout'"
out=$(verify "$RP"); [ $? = 0 ] && ok "a run prepared before the prune verifies" || no "verify after prune: $out"

# --- each strict run must pass an untouched refs-only check without accepting verification
git -C "$A" branch zz develop; git -C "$A" branch agent/gone develop
fresh() {
  local r; r=$(mkrun "$1")
  out=$(QARGI_VERIFY_REFS_ONLY=1 $DA local verify "$r" 2>&1) || no "(setup) $1 does not pass the untouched refs check: $out"
  [ ! -e "$T/s/runs/${r##*/}" ] || no "(setup) $1 unexpectedly saved output"
  echo "$r"
}
R=$(fresh r-branchf); git -C "$A" branch -f feature/fa "$(hand feature/fa)" >/dev/null
refused "$R" "an unjournaled git branch -f of feature/fa"
R=$(fresh r-updateref); git -C "$A" update-ref refs/heads/zz "$(hand zz)"
refused "$R" "an unjournaled git update-ref of a local branch"
R=$(fresh r-tag); git -C "$A" tag hand-made develop
refused "$R" "a hand-made tag"
R=$(fresh r-push); git -C "$A" push -q origin develop:refs/heads/elsewhere
refused "$R" "a push of a ref to the remote"
git -C "$A" push -q origin :refs/heads/elsewhere
R=$(fresh r-moved-again); $F start j1 >/dev/null 2>&1; git -C "$A" branch -f feature/j1 "$(hand feature/j1)" >/dev/null
refused "$R" "a journaled move that no longer leads to the ref's value"
R=$(fresh r-repo); $F start j2 >/dev/null 2>&1; tamper '.repo = "/elsewhere/other-repo"'
refused "$R" "a journal entry for a different repository"
R=$(fresh r-old); $F start j3 >/dev/null 2>&1; tamper '.epoch = 1 | .at = "1970-01-01T00:00:01Z"'
refused "$R" "a journal entry older than the run's start"
R=$(fresh r-deleted); git -C "$A" branch -D agent/gone >/dev/null
refused "$R" "a deleted branch that was not journaled"

# Removing the public mirror cannot return a privately verified run to strict mode.
git -C "$A" branch agent/pv develop
RPV=$(mkrun r-postverify); out=$(verify "$RPV") || no "(setup) r-postverify: $out"
rm -f "$RPV/verified"
git -C "$A" branch -f agent/pv "$(hand agent/pv)" >/dev/null
out=$(verify "$RPV"); rc=$?
[ "$rc" = 0 ] && grep -q "agent/pv fast-forwarded (a lead-side move after the run's passing verify)" <<<"$out" && ok "private verification survives deletion of the public marker" || no "post-verify fast-forward: rc=$rc $out"
git -C "$A" branch -f agent/pv "$(git -C "$A" commit-tree -m rewritten 'develop^{tree}')" >/dev/null
refused "$RPV" "a hand rewrite of an agent branch after a passing verify"
git -C "$A" branch -D agent/pv >/dev/null

# --- finish journals develop's move and the branch deletion
$F start fin >/dev/null 2>&1; task agent/t1 t1.txt t1; $F merge fin agent/t1 >/dev/null 2>&1
$F verify fin >/dev/null 2>&1
d0=$(sha develop); fin=$(sha feature/fin); t=$($F finish fin 2>&1 | tok); n=$(jn)
RF=$(fresh r-finish)                                     # strict: no passing verify yet
RF3=$(fresh r-finish3)                                   # strict too: cleaned without a verify of its own after the finish
RF2=$(mkrun r-finish2); $DA local verify "$RF2" >/dev/null 2>&1 || no "(setup) r-finish2 does not verify"   # after a passing verify
rd0=$(git --git-dir="$T/origin.git" rev-parse develop)
$F finish fin --plan "$t" --approved go >/dev/null 2>&1; rc=$?
d1=$(sha develop)
[ $rc = 0 ] && [ "$d1" != "$d0" ] && jhas develop "$d0" "$d1" && ok "feature finish journals develop's move" || no "finish: rc=$rc, journal $(tail -n +"$((n + 1))" "$J" 2>&1)"
jhas feature/fin "$fin" "$Z" && ok "and the deletion of the feature branch" || no "finish left no deletion line"
jq -e --arg o "$rd0" --arg n "$d1" --arg u "$T/origin" 'select(.remote == "origin" and .url == $u and .ref == "refs/heads/develop" and .old == $o and .new == $n and .verb == "feature:finish")' "$J" >/dev/null \
  && ok "and its push of develop to origin (remote origin, the origin URL, what origin had and what it has now)" || no "finish left no push line: $(tail -n 4 "$J")"
out=$($DA local verify "$RF" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q "develop moved by qargi feature finish" <<<"$out" && grep -q "develop on origin moved by qargi feature finish" <<<"$out" \
  && grep -q "feature/fin deleted by qargi feature finish" <<<"$out" && grep -q "origin/develop moved to what origin has" <<<"$out"; } \
  && ok "a run prepared before the finish verifies, and verify names develop's move and push, the deletion and the fetch" || no "verify after finish (strict): rc=$rc $out"
out=$($DA local verify "$RF2" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "feature/fin deleted by qargi feature finish\$" <<<"$out" && ok "after a passing verify too: the journaled deletion of the feature branch is accepted (fast-forwards alone were before), with no count of commits made with git: there was none" || no "verify after finish (lenient): rc=$rc $out"
echo '{}' > "$RF3/out/manifest.json"; out=$($DA local clean "$RF3" 2>&1); rc=$?
[ $rc = 0 ] && [ ! -e "$RF3" ] && grep -q "accepted, the lead's own move: develop moved by qargi feature finish" <<<"$out" && ok "clean accepts those moves and names them" || no "clean after finish: rc=$rc $out"

# --- a release
$REL verify 0.2.0 >/dev/null 2>&1; d0=$(sha develop)
rstart 0.2.0 --date 2026-01-02 >/dev/null 2>&1; rb=$(sha release/0.2.0)
jhas release/0.2.0 "$Z" "$rb" && [ "$rb" != "$Z" ] && ok "release start journals the new release branch" || no "release start left no journal line"
RR=$(fresh r-release)
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
jq -e --arg n "$rb" 'select(.remote == "origin" and .ref == "refs/heads/release/0.2.0" and .old == "0000000000000000000000000000000000000000" and .new == $n and .verb == "release:push")' "$J" >/dev/null \
  && ok "release push journals the new branch on origin" || no "release push left no push line: $(tail -n 2 "$J")"
m0=$(sha master); d0=$(sha develop); t=$($REL finish 0.2.0 | tok)
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
m1=$(sha master); d1=$(sha develop)
[ $rc = 0 ] && [ "$m1" != "$m0" ] && jhas master "$m0" "$m1" && jhas develop "$d0" "$d1" && jhas release/0.2.0 "$rb" "$Z" && ok "release finish journals master, develop and the release branch's deletion" || no "release finish: rc=$rc, lines $(tail -n 4 "$J" 2>&1)"
tg=$(git -C "$A" rev-parse refs/tags/0.2.0)
[ "$(jq -c --arg n "$tg" 'select(.ref == "refs/tags/0.2.0" and .old == "0000000000000000000000000000000000000000" and .new == $n and .verb == "release:finish")' "$J" | wc -l)" = 2 ] \
  && jq -e 'select(.remote == "origin" and .ref == "refs/heads/release/0.2.0" and .new == "0000000000000000000000000000000000000000")' "$J" >/dev/null \
  && ok "and the tag (in the repository and on origin) and the deletion of the release branch on origin" || no "release finish tag lines: $(grep tags "$J")"
out=$($DA local verify "$RR" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q "master moved by qargi release finish" <<<"$out" && grep -q "master on origin moved by qargi release finish" <<<"$out" \
  && grep -q "tag 0.2.0 created by qargi release finish" <<<"$out" && grep -q "tag 0.2.0 on origin created by qargi release finish" <<<"$out" \
  && grep -q "release/0.2.0 deleted by qargi release finish" <<<"$out"; } \
  && ok "a run prepared before the release verifies, and verify names every move, push and tag of the release" || no "verify after release: rc=$rc $out"

# --- the parking branch (answers repo.parking_branch, default scratch) fast-forwarded to develop by hand is accepted; nothing else of the kind
git -C "$A" branch scratch develop~1
R=$(fresh r-park); git -C "$A" branch -f scratch develop
out=$($DA local verify "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "scratch (the parking branch) fast-forwarded to develop" <<<"$out" && ok "a hand fast-forward of the parking branch to develop's tip is accepted and named" || no "parking ff: rc=$rc $out"
R=$(fresh r-park2); git -C "$A" branch -f scratch "$(hand scratch)"
refused "$R" "a hand move of the parking branch that does not end at develop's tip"
git -C "$A" branch -f scratch develop; git -C "$A" branch zz2 develop~1
R=$(fresh r-park3); git -C "$A" branch -f zz2 develop
refused "$R" "a hand fast-forward to develop of a branch that is not the parking branch"
jq '.repo.parking_branch = "zz2"' "$T/c/projects/app.json" > "$T/app.json" && mv "$T/app.json" "$T/c/projects/app.json"
git -C "$A" branch -f zz2 develop~1
R=$(fresh r-park4); git -C "$A" branch -f zz2 develop   # the answers of a run are the ones at its prepare, so the run is made after the change
out=$($DA local verify "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "zz2 (the parking branch)" <<<"$out" && ok "the parking branch is the one the answers name (repo.parking_branch)" || no "answers parking: rc=$rc $out"
jq 'del(.repo.parking_branch)' "$T/c/projects/app.json" > "$T/app.json" && mv "$T/app.json" "$T/c/projects/app.json"

# --- qargi ref record --rewrite: the lead rewrites an agent branch to a commit with the same tree, and verify accepts it as a rewrite
REF="$DA ref record --rewrite"
task agent/rw rw.txt one; o=$(sha agent/rw)
same() { git -C "$A" commit-tree -p "$1~1" -m "${2:-reworded}" "$1^{tree}"; }   # the same tree, another message
R=$(fresh r-rewrite); RL=$(mkrun r-rewrite2); $DA local verify "$RL" >/dev/null 2>&1
nw=$(same "$o"); n=$(jn)
out=$($REF agent/rw "$o" "$nw" --why "reworded the message" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(sha agent/rw)" = "$nw" ] && jq -e --arg o "$o" --arg n "$nw" 'select(.verb == "ref:rewrite" and .ref == "refs/heads/agent/rw" and .old == $o and .new == $n and .why == "reworded the message")' "$J" >/dev/null; } \
  && ok "ref record --rewrite moves the agent branch and journals the move with the reason" || no "rewrite: rc=$rc $out"
out=$($DA local verify "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "agent/rw moved by a rewrite (qargi ref record --rewrite: reworded the message)" <<<"$out" && ok "verify accepts the rewrite and names it as one" || no "verify after rewrite: rc=$rc $out"
out=$($DA local verify "$RL" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "agent/rw moved by a rewrite" <<<"$out" && ok "after a passing verify too (it is not a fast-forward)" || no "verify after rewrite (lenient): rc=$rc $out"
n=$(jn); cur=$(sha agent/rw)
dt=$(git -C "$A" commit-tree -p "$cur~1" -m "other content" "$(git -C "$A" rev-parse 'develop^{tree}')")
out=$($REF agent/rw "$cur" "$dt" --why "x" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "trees of OLD .* differ" <<<"$out" && [ "$(sha agent/rw)" = "$cur" ] && [ "$(jn)" = "$n" ] && ok "a NEW with another tree is refused: nothing moves, nothing is journaled" || no "other tree: rc=$rc $out"
out=$($REF agent/rw "$o" "$(same "$cur" again)" --why "x" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not at OLD" <<<"$out" && [ "$(sha agent/rw)" = "$cur" ] && [ "$(jn)" = "$n" ] && ok "a REF that is not at OLD is refused" || no "not at OLD: rc=$rc $out"
dv=$(sha develop)
out=$($REF develop "$dv" "$(same "$dv")" --why "x" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "only an agent/\* branch" <<<"$out" && [ "$(sha develop)" = "$dv" ] && ok "a branch that is not agent/* is refused" || no "develop rewrite: rc=$rc $out"
for bad in "agent/rw $cur $(same "$cur")" "--why x" "agent/rw $cur --why x"; do
  # shellcheck disable=SC2086
  out=$($REF $bad 2>&1); rc=$?
  [ $rc = 2 ] && [ "$(jn)" = "$n" ] && ok "ref record --rewrite $bad is a usage error" || no "usage $bad: rc=$rc $out"
done
out=$($DA ref record agent/rw "$cur" "$(same "$cur")" --why x 2>&1); [ $? = 2 ] && grep -q "needs --rewrite" <<<"$out" && ok "ref record without --rewrite is a usage error" || no "no --rewrite: $out"
R=$(fresh r-rewrite3); git -C "$A" branch -f agent/rw "$(same "$cur" "by hand")"
refused "$R" "a same-tree rewrite of an agent branch made by hand (not recorded)"
git -C "$A" branch -f agent/rw "$cur"
# clean follows the applied tip of a run through a recorded rewrite
$F start rwf >/dev/null 2>&1
RW=$(seriesrun rwc rwc.go feature/rwf); $DA review apply "$RW" >/dev/null 2>&1 || no "(setup) apply rwc"
at=$(sha agent/rwc); at2=$(same "$at" "names: change rwc, reworded")
$REF agent/rwc "$at" "$at2" --why "reworded" >/dev/null 2>&1 && $F merge rwf agent/rwc >/dev/null 2>&1 || no "(setup) rewrite and merge rwc"
out=$($DA local clean "$RW" 2>&1); rc=$?
[ $rc = 0 ] && [ ! -e "$RW" ] && ok "clean counts a run as merged when the commit its applied tip was rewritten to is merged" || no "clean after rewrite: rc=$rc $out"

# the lead rewrote an applied branch by hand: the refusals of clean and close name the fix, with the branch and both tips filled in
RH=$(seriesrun rwh rwh.go feature/rwf); $DA review apply "$RH" >/dev/null 2>&1 || no "(setup) apply rwh"
ht=$(sha agent/rwh); ht2=$(same "$ht" "names: change rwh, reworded by hand")
git -C "$A" branch -f agent/rwh "$ht2"
out=$($DA local clean "$RH" 2>&1); rc=$?
if [ $rc = 1 ] && grep -q "not merged into any branch yet" <<<"$out" && grep -qF "qargi ref record --rewrite agent/rwh $ht $ht2 --why" <<<"$out" && grep -qF "git branch -f agent/rwh $ht" <<<"$out"; then
  ok "clean of a run whose applied branch was rewritten by hand names qargi ref record --rewrite with the branch and both tips"
else no "clean hint: rc=$rc $out"; fi
out=$($DA local close "$RH" --applied-by-am 2>&1); rc=$?
if [ $rc = 1 ] && grep -q "merge that branch" <<<"$out" && grep -qF "qargi ref record --rewrite agent/rwh $ht $ht2 --why" <<<"$out" && [ -d "$RH" ]; then
  ok "close --applied-by-am names the same fix"
else no "close hint: rc=$rc $out"; fi
# The public mirror is member-writable; the completed private record supplies the diagnostic.
RHREC=$T/s/apply/${RH##*/}.json
cp -p "$RH/applied" "$T/rh.applied" && cp -p "$RHREC" "$T/rh.rec" || no "(setup) save rwh records"
for how in absent poisoned; do
  if [ "$how" = absent ]; then rm -f "$RH/applied"; else printf 'agent/poisoned %040d now\n' 0 > "$RH/applied"; fi
  out=$($DA local close "$RH" --applied-by-am 2>&1); rc=$?
  if [ "$rc" = 1 ] && grep -qF "qargi ref record --rewrite agent/rwh $ht $ht2 --why" <<<"$out" && ! grep -q "agent/poisoned" <<<"$out" && [ -d "$RH/clone" ] && cmp -s "$RHREC" "$T/rh.rec"; then
    ok "close uses the private record with public applied $how, keeping clone and record"
  else no "close hint, applied $how: rc=$rc $out"; fi
done
cp -p "$T/rh.applied" "$RH/applied" || no "(setup) restore rwh applied"
# Test-only status injection models unfinished records; restore the completed record afterwards.
for st in started built; do
  jq --arg s "$st" '.status = $s' "$T/rh.rec" > "$T/rh.$st" && cp "$T/rh.$st" "$RHREC" || no "(setup) record $st"
  out=$($DA local close "$RH" --applied-by-am 2>&1); rc=$?
  if [ "$rc" = 1 ] && grep -q "run has an authoritative apply record: finish/merge it, then clean" <<<"$out" && ! grep -q "merge that branch" <<<"$out" && [ -d "$RH/clone" ] && cmp -s "$RH/applied" "$T/rh.applied" && cmp -s "$RHREC" "$T/rh.$st"; then
    ok "close refuses $st early, keeping clone and both records"
  else no "close with apply $st: rc=$rc $out"; fi
done
cp -p "$T/rh.rec" "$RHREC" && cmp -s "$RHREC" "$T/rh.rec" || no "(setup) restore the done record of rwh"
# the sentence is the fix in full: do what it says, and clean follows the rewrite once the branch is merged
git -C "$A" branch -f agent/rwh "$ht" && $REF agent/rwh "$ht" "$ht2" --why "reworded by hand" >/dev/null 2>&1 || no "(setup) record the rewrite of rwh"
out=$($DA local clean "$RH" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not merged into any branch yet" <<<"$out" && ! grep -q "ref record --rewrite" <<<"$out" && ok "once the rewrite is recorded the hint is gone (the branch is not merged yet)" || no "recorded hint: rc=$rc $out"
$F merge rwf agent/rwh >/dev/null 2>&1 || no "(setup) merge rwh"
out=$($DA local clean "$RH" 2>&1); rc=$?
[ $rc = 0 ] && [ ! -e "$RH" ] && ok "after the recorded rewrite is merged, clean removes the run" || no "clean after record: rc=$rc $out"
# the two commands are meant to be pasted: a branch name that git allows and the shell reads (a $ and a ;) is printed quoted
RQ=$(seriesrun rwq rwq.go feature/rwf); QB='agent/q$x;y'; $DA review apply "$RQ" --branch "$QB" >/dev/null 2>&1 || no "(setup) apply rwq"
qt=$(sha "$QB"); qt2=$(same "$qt" "names: change rwq, reworded by hand"); git -C "$A" branch -f "$QB" "$qt2"
out=$($DA local clean "$RQ" 2>&1); rc=$?
QQ=$(printf '%q' "$QB")
if [ $rc = 1 ] && grep -qF "git branch -f $QQ $qt," <<<"$out" && grep -qF "qargi ref record --rewrite $QQ $qt $qt2 --why" <<<"$out" && [ "$QQ" != "$QB" ]; then
  ok "the hint prints a branch name with a \$ and a ; quoted for the shell"
else no "quoted hint: rc=$rc $out"; fi
git -C "$A" branch -f "$QB" "$qt"
# a run whose directory is gone (the saved copy holds the applied record): the refusal names the fix as well
RV=$(seriesrun rwv rwv.go feature/rwf); $DA review apply "$RV" >/dev/null 2>&1 || no "(setup) apply rwv"
vt=$(sha agent/rwv); vt2=$(same "$vt" "names: change rwv, reworded by hand"); git -C "$A" branch -f agent/rwv "$vt2"
SVV=$T/s/runs/$(basename "$RV"); printf 'agent/rwv %s now\n' "$vt" > "$SVV/applied" && rm -rf "$RV" || no "(setup) vanish rwv"
out=$($DA local clean "$RV" 2>&1); rc=$?
[ $rc = 1 ] && [ ! -e "$RV" ] && grep -q "not merged into any branch yet" <<<"$out" && grep -qF "qargi ref record --rewrite agent/rwv $vt $vt2 --why" <<<"$out" \
  && ok "the refusal for a run whose directory is gone names the fix too" || no "gone hint: rc=$rc $out"
git -C "$A" branch -f agent/rwv "$vt"
# the other cases keep their text and name no rewrite: the tip is the journaled one
RN=$(seriesrun rwn rwn.go feature/rwf); $DA review apply "$RN" >/dev/null 2>&1 || no "(setup) apply rwn"
out=$($DA local clean "$RN" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not merged into any branch yet: qargi feature merge NAME agent/rwn" <<<"$out" && ! grep -q "rewrite" <<<"$out" && ok "an unmerged branch at its journaled tip: the refusal is as before, no rewrite is named" || no "plain refusal: rc=$rc $out"
out=$($DA local close "$RN" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "merge that branch" <<<"$out" && ! grep -q "rewrite" <<<"$out" && ok "close of an applied run at its journaled tip: as before" || no "plain close refusal: rc=$rc $out"

# --- a branch the lead committed on with git, then deleted by a verb: a run prepared before those commits still verifies.
# The journal has no line for a commit made with git (the fix of a release in the worktree of release fix, the entries of a hotfix, a commit
# in a feature's worktree, a push by hand), so the line of the deletion started at a tip the journal did not lead to from the run's snapshot.
# The deleting verb now writes the steps up to the tip it deletes (journal_reach), in the repository and for origin.
use() { export QARGI_PROJECT=$1; A=$T/$1; }
# byhand BRANCH FILE [push]: a commit made with git on BRANCH in a worktree of it, as the lead commits a fix; with push it is pushed by hand too
byhand() {
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q "$w" "$1"
  echo "$2" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "by hand: $2"; git -C "$A" worktree remove --force "$w"
  [ -z "${3:-}" ] || git -C "$A" push -q origin "$1"
}
# approve COMMAND...: the plan of an owner verb, then the same command with its token and an approval. The plan's text is kept in $T/plan (planned prints it).
approve() { local p t; p=$("$@" 2>&1); printf '%s\n' "$p" > "$T/plan"; t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; "$@" --plan "$t" --approved go 2>&1; }
planned() { cat "$T/plan"; }
# takes N NAME OLD NEW [INDENT]: the line of a plan that says the deletion of NAME takes N commits made with git, from OLD to NEW, into the journal
takes() {
  local n="$1 commits" them=them
  [ "$1" != 1 ] || { n="1 commit"; them=it; }
  printf '%sjournal: takes %s made with git on %s (%s..%s): journaled with the deletion, so a run prepared before %s still verifies\n' "${5:-  }" "$n" "$2" "${3:0:7}" "${4:0:7}" "$them"
}
# reach REF-SUFFIX OLD NEW VERB [remote]: the journal holds the step OLD -> NEW of that branch, written by VERB with a reason that names git, on that side
# (a line that is not JSON is skipped, as the readers of qargi skip it: a test puts one in the journal)
reach() {
  jq -Re --arg r "$1" --arg o "$2" --arg n "$3" --arg v "$4" --arg side "${5:-local}" \
    'fromjson? | select((.ref | endswith($r)) and .old == $o and .new == $n and .verb == $v and ((.why // "") | test("with git")) and (if $side == "remote" then .remote == "origin" else (has("remote") | not) end))' "$J" >/dev/null 2>&1
}
# gone_flow VERSION SLUG LABEL [origin]: in the project of $A a release branch, a feature branch and an agent branch exist and the journal knows each
# (with origin: also on origin, the release by release push, the other two pushed by hand and noted). A run is prepared. The lead then commits with git
# on each branch, twice on the release (with origin: the first fix goes to origin through release push, the second and the other two branches by hand, and
# nothing is noted), a task merge follows the commit on the feature, and release finish, feature finish and branch prune delete the three branches (with
# origin: there too). The run must verify and name each verb, with the number of commits made with git that the verb took. A second run, prepared after
# the first of the two commits on the release branch (with origin: after release push took it there), must verify as well and count the one commit left.
gone_flow() {
  local v=$1 lbl=$3 org=${4:-} fr fm r0 r1 r2 f0 f1 z0 z1 out outm rc said pf pr pp bad gw=" made with git, taken by the verb)"
  $REL verify "$v" >/dev/null 2>&1; rstart "$v" --date 2026-02-02 --allow-empty-notes >/dev/null 2>&1 || no "(setup) $lbl: release start $v"
  $F start gf >/dev/null 2>&1; task agent/gz gz.txt one; $DA ref note agent/gz >/dev/null 2>&1 || no "(setup) $lbl: note agent/gz"
  if [ -n "$org" ]; then
    approve $REL push "$v" >/dev/null || no "(setup) $lbl: release push $v"
    git -C "$A" push -q origin feature/gf agent/gz && $DA ref note origin/feature/gf origin/agent/gz >/dev/null 2>&1 || no "(setup) $lbl: push and note the feature and agent branches"
  fi
  fr=$(mkrun "$2"); out=$(QARGI_VERIFY_REFS_ONLY=1 $DA local verify "$fr" 2>&1) || no "(setup) $lbl: the run does not pass the untouched refs check: $out"
  r0=$(sha "release/$v"); f0=$(sha feature/gf); z0=$(sha agent/gz)
  byhand "release/$v" fix.txt; r1=$(sha "release/$v")
  [ -z "$org" ] || approve $REL push "$v" >/dev/null || no "(setup) $lbl: release push of the first fix"
  fm=$(mkrun "$2-mid"); out=$(QARGI_VERIFY_REFS_ONLY=1 $DA local verify "$fm" 2>&1) || no "(setup) $lbl: the run prepared at the first fix does not pass the untouched refs check: $out"
  byhand "release/$v" fix2.txt "$org"; byhand feature/gf lead.txt "$org"; byhand agent/gz two.txt "$org"
  r2=$(sha "release/$v"); f1=$(sha feature/gf); z1=$(sha agent/gz)
  [ -n "$org" ] || $REL verify "$v" >/dev/null 2>&1
  $F merge gf agent/gz >/dev/null 2>&1 && $F verify gf >/dev/null 2>&1 || no "(setup) $lbl: merge and verify the feature"
  out=$(approve $F finish gf) || no "(setup) $lbl: feature finish: $out"; said=$out; pf=$(planned)
  out=$(approve $REL finish "$v") || no "(setup) $lbl: release finish: $out"; said+=$'\n'$out; pr=$(planned)
  out=$(approve $DA branch prune ${org:+--remote}) || no "(setup) $lbl: branch prune: $out"; said+=$'\n'$out; pp=$(planned)
  # each plan says how many commits made with git the deletion takes into the journal, and from which commit to which
  grep -qxF "$(takes 1 feature/gf "$f0" "$f1")" <<<"$pf" && grep -qxF "$(takes 2 "release/$v" "$r0" "$r2")" <<<"$pr" && grep -qxF "$(takes 1 agent/gz "$z0" "$z1" '    ')" <<<"$pp" \
    && ok "$lbl: the plans of feature finish, release finish and branch prune each list the commits made with git that the deletion takes: their number and range" || no "$lbl: plan lines: $(grep -h 'journal:' <<<"$pf"$'\n'"$pr"$'\n'"$pp")"
  if [ -n "$org" ]; then
    grep -qxF "$(takes 1 origin/feature/gf "$f0" "$f1")" <<<"$pf" && grep -qxF "$(takes 1 "origin/release/$v" "$r1" "$r2")" <<<"$pr" && grep -qxF "$(takes 1 origin/agent/gz "$z0" "$z1" '    ')" <<<"$pp" \
      && ok "$lbl: and the ones pushed by hand to the branch they delete on origin (the push release push made is not among them)" || no "$lbl: plan lines for origin: $(grep -h 'journal:' <<<"$pf"$'\n'"$pr"$'\n'"$pp")"
  else
    ! grep -q "journal: takes .* on origin/" <<<"$pf"$'\n'"$pr"$'\n'"$pp" && ok "$lbl: no plan names a branch of origin" || no "$lbl: a plan names a branch of origin: $(grep -h 'journal:' <<<"$pf"$'\n'"$pr"$'\n'"$pp")"
  fi
  # a verb that journaled the steps of a branch prints no note that the journal does not lead to the tip it deleted (another branch of the prune may get one)
  ! grep -E "does not lead to .*, where (origin/)?(release/$v|feature/gf|agent/gz) was deleted" <<<"$said" || no "$lbl: a note for a branch whose steps were journaled"
  { [ "$(sha "release/$v")" = "$Z" ] && [ "$(sha feature/gf)" = "$Z" ] && [ "$(sha agent/gz)" = "$Z" ] && [ "$r1" != "$r0" ] && [ "$r2" != "$r1" ] && [ "$f1" != "$f0" ] && [ "$z1" != "$z0" ]; } \
    || no "(setup) $lbl: the three branches are not deleted, or a commit by hand did not move one"
  reach "release/$v" "$r0" "$r1" release:finish && reach "release/$v" "$r1" "$r2" release:finish && jhas "release/$v" "$r2" "$Z" \
    && ok "$lbl: release finish journals each commit the lead made on the release branch with git, one step a commit, then the deletion at the released head" || no "$lbl: no steps $r0 -> $r1 -> $r2 before the deletion of release/$v: $(grep "release/$v" "$J" | tail -n 5)"
  reach feature/gf "$f0" "$f1" feature:finish && ok "$lbl: feature finish journals the commit made with git on the feature branch (a journaled task merge followed it)" || no "$lbl: no step $f0 -> $f1 of feature/gf: $(grep 'feature/gf' "$J" | tail -n 5)"
  reach agent/gz "$z0" "$z1" branch:prune && ok "$lbl: branch prune journals the commit made with git on the agent branch" || no "$lbl: no step $z0 -> $z1 of agent/gz: $(grep 'agent/gz' "$J" | tail -n 4)"
  # the steps are written together, and each is a whole journal line: every field, the reason, and for a branch of origin the remote and its URL
  bad=$(jq -c 'select((.why // "") | test("with git"))
    | select((keys - ["remote", "url"]) != ["at","by","epoch","new","old","project","ref","repo","verb","why"] or (.old | test("^[0-9a-f]{40}$") | not) or (.new | test("^[0-9a-f]{40}$") | not)
        or .old == .new or (.epoch | type) != "number" or (.by | length) == 0 or (.project | length) == 0 or has("remote") != has("url") or (has("remote") and (.remote != "origin" or (.url | length) == 0)))' "$J" 2>&1 | head -n 3)
  [ -z "$bad" ] && [ "$(jq -c 'select((.why // "") | test("with git"))' "$J" | wc -l)" -ge 4 ] \
    && ok "$lbl: each step a deleting verb wrote is a whole journal line: at, epoch, verb, project, repo, ref, old, new, by and the reason (and remote and url for origin)" || no "$lbl: step lines: $bad"
  out=$(verify "$fr"); rc=$?
  [ $rc = 0 ] && ok "$lbl: a run prepared before the lead committed on the release, feature and agent branches verifies after the verbs deleted them" || no "$lbl: verify after the deletions: rc=$rc $out"
  grep -qF "release/$v deleted by qargi release finish (2 commits$gw" <<<"$out" && ok "$lbl: verify names release finish for the deleted release branch, and the two commits made with git that it took" || no "$lbl: release/$v is not accepted as deleted by release finish with its 2 commits: $(grep "release/$v" <<<"$out")"
  grep -qF "feature/gf deleted by qargi feature finish (1 commit$gw, qargi feature merge" <<<"$out" && ok "$lbl: and feature finish for the deleted feature branch, with the one commit made with git; the task merge is named without a count" || no "$lbl: feature/gf is not accepted as deleted by feature finish with its 1 commit: $(grep 'feature/gf' <<<"$out")"
  grep -qF "agent/gz deleted by qargi branch prune (1 commit$gw" <<<"$out" && ok "$lbl: and branch prune for the deleted agent branch, with the one commit made with git" || no "$lbl: agent/gz is not accepted as deleted by branch prune with its 1 commit: $(grep 'agent/gz' <<<"$out")"
  # the run prepared at the first of the two commits made with git on the release branch: the journal leads on from that commit
  outm=$(verify "$fm"); rc=$?
  [ $rc = 0 ] && ok "$lbl: a run prepared at a commit the lead made with git on the release branch, before the next one, verifies after release finish deleted the branch" || no "$lbl: verify of the run prepared at the first fix: rc=$rc $outm"
  grep -qF "release/$v deleted by qargi release finish (1 commit$gw" <<<"$outm" && ok "$lbl: and verify counts the one commit made with git after that run was prepared" || no "$lbl: release/$v for the run prepared at the first fix: $(grep "release/$v" <<<"$outm")"
  [ -n "$org" ] || return 0
  # origin: release push journaled its own pushes of the release, the second fix went there by hand; so did the feature and agent branches after the lead's notes of them
  reach "release/$v" "$r1" "$r2" release:finish remote && reach feature/gf "$f0" "$f1" feature:finish remote && reach agent/gz "$z0" "$z1" branch:prune remote \
    && ok "$lbl: release finish, feature finish and branch prune journal the push by hand of the branch they delete on origin" || no "$lbl: no step for origin: $(grep -E "release/$v|feature/gf|agent/gz" "$J" | grep origin | tail -n 8)"
  grep -qF "release/$v on origin deleted by qargi release push, qargi release finish (1 commit$gw" <<<"$out" && ok "$lbl: verify names release push and release finish for the release branch deleted on origin: the push release push made has no count, the one by hand is counted with release finish" || no "$lbl: release/$v on origin: $(grep "release/$v" <<<"$out")"
  grep -qF "feature/gf on origin deleted by qargi feature finish (1 commit$gw" <<<"$out" && grep -qF "agent/gz on origin deleted by qargi branch prune (1 commit$gw" <<<"$out" \
    && ok "$lbl: and feature finish and branch prune for the branches deleted on origin, each with the one commit pushed by hand" || no "$lbl: the branches of origin: $(grep -E 'feature/gf|agent/gz' <<<"$out")"
  grep -qF "release/$v on origin deleted by qargi release finish (1 commit$gw" <<<"$outm" && ok "$lbl: the run prepared after release push took the first fix to origin: the push by hand of the second is the one commit counted there" || no "$lbl: release/$v on origin for the run prepared at the first fix: $(grep "release/$v" <<<"$outm")"
}
jq '.branches.delete_merged = "local+remote"' "$T/c/projects/app.json" > "$T/app.json" && mv "$T/app.json" "$T/c/projects/app.json"   # feature finish deletes the branch on origin too
gone_flow 0.3.0 gone-origin "with an origin" origin
# a repository with no origin
git init -q -b master "$T/solo"; echo 0.1.0 > "$T/solo/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$T/solo/CHANGELOG.md"
git -C "$T/solo" add -A && git -C "$T/solo" commit -q -m base && git -C "$T/solo" branch develop && git -C "$T/solo" checkout -q -b parked
jq -n --arg p "$T/solo" '{schema:1, project:"solo", methodology:"gitflow", repo:{url:"https://github.com/acme/solo", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/solo.json"
use solo
# a hotfix: its content is always a commit the lead makes on the branch after start
rstart 0.1.1 --hotfix --date 2026-02-01 --allow-empty-notes >/dev/null 2>&1 || no "(setup) hotfix start"
RH=$(mkrun gone-hotfix); h0=$(sha hotfix/0.1.1)
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q "$w" hotfix/0.1.1
sed -i 's/^## \[0\.1\.1\].*/&\n\n- the fix/' "$w/CHANGELOG.md"; echo fix > "$w/hot.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "the hotfix"; git -C "$A" worktree remove --force "$w"
h1=$(sha hotfix/0.1.1)
$REL verify 0.1.1 --hotfix >/dev/null 2>&1; out=$(approve $REL finish 0.1.1 --hotfix) || no "(setup) hotfix finish: $out"
[ "$(sha hotfix/0.1.1)" = "$Z" ] && [ "$h1" != "$h0" ] && reach hotfix/0.1.1 "$h0" "$h1" hotfix:finish && jhas hotfix/0.1.1 "$h1" "$Z" \
  && ok "local only: hotfix finish journals the hotfix the lead committed with git, then the deletion of the branch" || no "hotfix finish: $(grep 'hotfix/0.1.1' "$J" | tail -n 4)"
out=$(verify "$RH"); rc=$?
[ $rc = 0 ] && grep -qF "hotfix/0.1.1 deleted by qargi hotfix finish (1 commit made with git, taken by the verb)" <<<"$out" && ok "local only: a run prepared before the hotfix was committed verifies after hotfix finish, which verify names with the one commit made with git" || no "verify after hotfix finish: rc=$rc $out"
gone_flow 0.2.0 gone-local "local only"
# what no verb did stays refused: a branch deleted by hand, a branch rewritten by hand whose deletion a verb then journaled at the other tip, and a
# branch whose tip is further from what the journal has than the steps a verb writes (JOURNAL_REACH_MAX, 500 commits of the first-parent line)
$F start hd >/dev/null 2>&1; $F start ot >/dev/null 2>&1; task agent/ot ot.txt one; task agent/far far.txt one; task agent/un un.txt one
$DA ref note agent/ot agent/far >/dev/null 2>&1 || no "(setup) note agent/ot and agent/far"   # agent/un is made by hand and never noted
RN=$(mkrun gone-hand); hd0=$(sha feature/hd); ot0=$(sha agent/ot); far0=$(sha agent/far); un0=$(sha agent/un)
git -C "$A" branch -D feature/hd >/dev/null
ot1=$(git -C "$A" commit-tree -p develop -m "rewritten by hand" "agent/ot^{tree}"); git -C "$A" branch -f agent/ot "$ot1" >/dev/null
far1=$far0; for _ in $(seq 1 501); do far1=$(git -C "$A" commit-tree -p "$far1" -m "one more by hand" "$far0^{tree}"); done; git -C "$A" branch -f agent/far "$far1" >/dev/null
byhand agent/un un2.txt; un1=$(sha agent/un)
$F merge ot agent/ot >/dev/null 2>&1 && $F merge ot agent/far >/dev/null 2>&1 && $F merge ot agent/un >/dev/null 2>&1 || no "(setup) merge the rewritten agent/ot, the long agent/far and the unnoted agent/un"
n=$(jn); out=$(approve $DA branch prune) || no "(setup) prune agent/ot, agent/far and agent/un: $out"
[ "$(sha agent/ot)" = "$Z" ] && jhas agent/ot "$ot1" "$Z" && [ "$(sha agent/far)" = "$Z" ] && jhas agent/far "$far1" "$Z" && [ "$(sha agent/un)" = "$Z" ] && jhas agent/un "$un1" "$Z" && [ "$un1" != "$un0" ] && [ "$(jn)" = $((n + 3)) ] \
  && ok "branch prune of a branch rewritten by hand, of one 501 commits past what the journal has and of one the journal never had journals each deletion at the tip it deleted and no step" || no "prune of the rewritten, the long and the unnoted branch: $(tail -n +"$((n + 1))" "$J" | head -n 6)"
# it says so, one line a branch on stderr, with the reason: a run prepared while the branch was at another commit will be refused
will="qargi local verify will refuse a run prepared earlier"
[ "$(grep -c "^note: the journal does not lead to " <<<"$out")" = 3 ] \
  && grep -q "^note: the journal does not lead to ${ot1:0:7}, where agent/ot was deleted (no commit the journal has it at is on its first-parent line: it was rewritten by hand.*): $will, while agent/ot was at another commit\$" <<<"$out" \
  && ok "pruning the branch rewritten by hand prints one note: the journal does not lead to the deleted tip, the branch was rewritten, verify will refuse an earlier run" || no "note for the rewritten branch: $(grep 'agent/ot' <<<"$out")"
# and the plan said so before the approval, with the same reason: nothing will be journaled for these branches, a run prepared earlier will be refused
pl=$(planned); pw="qargi local verify will refuse a run prepared earlier"
grep -qxF "    journal: no step will be journaled for agent/ot: the journal does not lead to ${ot1:0:7} (no commit the journal has it at is on its first-parent line: it was rewritten by hand, or a merge made by hand left that commit behind a second parent): $pw, while agent/ot was at another commit" <<<"$pl" \
  && grep -qxF "    journal: no step will be journaled for agent/far: the journal does not lead to ${far1:0:7} (no commit the journal has it at is within 500 commits of its tip on its first-parent line): $pw, while agent/far was at another commit" <<<"$pl" \
  && grep -qxF "    journal: no step will be journaled for agent/un: the journal does not lead to ${un1:0:7} (the journal has no line of it: it was made by hand and not noted with qargi ref note): $pw, while agent/un was at another commit" <<<"$pl" \
  && ok "the plan of that prune says it for each of the three branches before the approval: no step will be journaled, why, and that verify will refuse a run prepared earlier" || no "plan lines for the branches no step leads to: $(grep 'journal:' <<<"$pl")"
[ "$(grep -c 'journal: ' <<<"$pl")" = 3 ] && ok "and for no other branch of the plan" || no "journal lines of that plan: $(grep 'journal: ' <<<"$pl")"
grep -q "^note: the journal does not lead to ${far1:0:7}, where agent/far was deleted (no commit the journal has it at is within 500 commits of its tip on its first-parent line): $will" <<<"$out" \
  && ok "the branch 501 commits past what the journal has: the note names the bound of 500 commits" || no "note for the long branch: $(grep 'agent/far' <<<"$out")"
grep -q "^note: the journal does not lead to ${un1:0:7}, where agent/un was deleted (the journal has no line of it: it was made by hand and not noted with qargi ref note): $will" <<<"$out" \
  && ok "the branch the journal never had: the note says it was made by hand and not noted" || no "note for the unnoted branch: $(grep 'agent/un' <<<"$out")"
out=$(verify "$RN"); rc=$?
[ $rc != 0 ] && grep -qF "branch deleted: refs/heads/feature/hd (was $hd0) (not in the lead's ref journal)" <<<"$out" \
  && ok "a branch deleted by hand (git branch -D, no verb) is still refused, with the tip it was at" || no "hand deletion: rc=$rc $out"
[ $rc != 0 ] && grep -qF "branch deleted: refs/heads/agent/ot (was $ot0) (not in the lead's ref journal)" <<<"$out" \
  && ok "a deletion journaled for one tip does not accept the deletion of the branch at another tip" || no "deletion at another tip: rc=$rc $out"
[ $rc != 0 ] && grep -qF "branch deleted: refs/heads/agent/far (was $far0) (not in the lead's ref journal)" <<<"$out" \
  && ok "nor the deletion of a branch whose deleted tip is more than 500 commits past the tip the journal has" || no "deletion beyond the bound: rc=$rc $out"
[ $rc != 0 ] && grep -qF "branch deleted: refs/heads/agent/un (was $un0) (not in the lead's ref journal)" <<<"$out" \
  && ok "nor the deletion of a branch the journal never had, at a later tip than the run saw: what each note said" || no "deletion of the unnoted branch: rc=$rc $out"
# a verb journaled a move of the branch (A -> B, a task merge), the lead put the branch back at A with git and committed C there, and the finish
# deletes it at C: a journal line starts at A already, but it goes to B, so the step A -> C is written all the same. A run that had the branch at A
# then finds the deletion; one that had it at B does not, since B is no longer on the branch and no line starts there.
task agent/rs1 rs1.txt one; $DA ref note agent/rs1 >/dev/null 2>&1 || no "(setup) note agent/rs1"
$F start rs >/dev/null 2>&1; rsa=$(sha feature/rs); RSA=$(mkrun gone-reset-a)
$F merge rs agent/rs1 >/dev/null 2>&1 || no "(setup) merge agent/rs1 into feature/rs"
rsb=$(sha feature/rs); RSB=$(mkrun gone-reset-b)
git -C "$A" branch -f feature/rs "$rsa" >/dev/null; byhand feature/rs reset.txt; rsc=$(sha feature/rs)
$F verify rs >/dev/null 2>&1; n=$(jn); out=$($F finish rs 2>&1)
grep -qxF "$(takes 1 feature/rs "$rsa" "$rsc")" <<<"$out" && [ "$(jn)" = "$n" ] && [ "$(sha feature/rs)" = "$rsc" ] \
  && ok "the plan of the finish lists that step as one commit made with git, from the commit the journal has to the new one, and writes nothing" || no "plan of the finish after the reset: lines $n -> $(jn): $out"
out=$(approve $F finish rs) || no "(setup) finish of the feature put back and committed on: $out"
{ [ "$rsb" != "$rsa" ] && [ "$rsc" != "$rsb" ] && [ "$(git -C "$A" rev-parse "$rsc~1")" = "$rsa" ] && jhas feature/rs "$rsa" "$rsb" && [ "$(sha feature/rs)" = "$Z" ]; } \
  || no "(setup) feature/rs was not merged into (A -> B, journaled), put back at A, committed on (C) and finished"
reach feature/rs "$rsa" "$rsc" feature:finish && jhas feature/rs "$rsc" "$Z" \
  && ok "a branch put back with git to a commit a journal line starts at, and committed on there: the finish journals the step from that commit to the new one" || no "no step $rsa -> $rsc of feature/rs: $(grep 'feature/rs' "$J" | tail -n 5)"
out=$(verify "$RSA"); rc=$?
[ $rc = 0 ] && grep -qF "feature/rs deleted by qargi feature finish (1 commit made with git, taken by the verb)" <<<"$out" && ok "and a run that had the branch at that commit verifies after the finish, which verify names with the one commit made with git" || no "verify of the run at A after the reset: rc=$rc $out"
out=$(verify "$RSB"); rc=$?
[ $rc != 0 ] && grep -qF "branch deleted: refs/heads/feature/rs (was $rsb) (not in the lead's ref journal)" <<<"$out" \
  && ok "while a run that had it at the tip the lead dropped is still refused: no line starts there" || no "verify of the run at the dropped tip: rc=$rc $out"
# exactly at the bound: a branch deleted 500 commits past the commit the journal has it at gets all 500 steps, in order, and the run verifies (501 got none, above).
# A branch the lead notes with the very reason those steps carry is a note all the same: its line is the lead's text and is not counted as a commit a verb took.
task agent/at at.txt one; $DA ref note agent/at >/dev/null 2>&1 || no "(setup) note agent/at"
RB=$(mkrun gone-bound); at0=$(sha agent/at)
at1=$at0; for _ in $(seq 1 500); do at1=$(git -C "$A" commit-tree -p "$at1" -m "one more by hand" "$at0^{tree}"); done; git -C "$A" branch -f agent/at "$at1" >/dev/null
git -C "$A" branch agent/nt develop; $DA ref note agent/nt --why "a commit made on the branch with git; the verb took the branch with it" >/dev/null 2>&1 || no "(setup) note agent/nt with the reason of a step"
$F merge ot agent/at >/dev/null 2>&1 || no "(setup) merge the branch 500 commits past the journal"
n=$(jn); out=$(approve $DA branch prune) || no "(setup) prune agent/at: $out"
grep -qxF "$(takes 500 agent/at "$at0" "$at1" '    ')" <<<"$(planned)" && ok "the plan of the prune lists the 500 commits made with git and their range" || no "plan of the prune at the bound: $(planned | grep -v '^plan token')"
steps=$(jq -sc --arg o "$at0" --arg n "$at1" '[.[] | select(.ref == "refs/heads/agent/at" and .verb == "branch:prune" and ((.why // "") | test("with git")))] as $l
  | [($l | length), ($l[0].old == $o), ($l[-1].new == $n), ([range(1; $l | length) | select($l[.].old != $l[. - 1].new)] | length), ($l | map(.at) | unique | length)]' "$J")
[ "$(sha agent/at)" = "$Z" ] && [ "$steps" = "[500,true,true,0,1]" ] && jhas agent/at "$at1" "$Z" && [ "$(jn)" = $((n + 501)) ] && ! grep -q "does not lead to" <<<"$out" \
  && ok "branch prune of a branch exactly 500 commits past what the journal has journals the 500 steps, each from one commit to the next and all at one time, then the deletion, and prints no note" \
  || no "prune at the bound: steps $steps, lines $n -> $(jn): $(grep 'does not lead' <<<"$out")"
out=$(verify "$RB"); rc=$?
[ $rc = 0 ] && grep -qF "agent/at deleted by qargi branch prune (500 commits made with git, taken by the verb)" <<<"$out" \
  && ok "and a run prepared before those 500 commits verifies: verify counts them with branch prune" || no "verify at the bound: rc=$rc $(grep -v 'warning: --scratch' <<<"$out" | head -n 12)"
grep -q "agent/nt created by qargi ref note\$" <<<"$out" && ok "a branch noted with the reason of a step is named as a note, with no count" || no "the noted branch: $(grep 'agent/nt' <<<"$out")"
use app
# on origin too: a branch pushed by hand and never noted, then deleted there by branch prune --remote, gets the note with origin's name of it
$F start po >/dev/null 2>&1; task agent/po po.txt one; git -C "$A" push -q origin agent/po; byhand agent/po po2.txt push; po1=$(sha agent/po)
$F merge po agent/po >/dev/null 2>&1 || no "(setup) merge agent/po"
out=$(approve $DA branch prune --remote) || no "(setup) prune agent/po here and on origin: $out"
[ "$(sha agent/po)" = "$Z" ] && [ -z "$(git -C "$A" ls-remote origin refs/heads/agent/po)" ] \
  && grep -q "^note: the journal does not lead to ${po1:0:7}, where origin/agent/po was deleted (the journal has no line of it: it was pushed by hand, or by an agent, and not noted with qargi ref note): $will, while origin/agent/po was at another commit\$" <<<"$out" \
  && ok "a branch of origin the journal never had, deleted by branch prune --remote: the note names origin/NAME and says it was pushed and not noted" || no "note for the branch of origin: $(grep 'agent/po' <<<"$out")"
grep -qxF "    journal: no step will be journaled for origin/agent/po: the journal does not lead to ${po1:0:7} (the journal has no line of it: it was pushed by hand, or by an agent, and not noted with qargi ref note): $will, while origin/agent/po was at another commit" <<<"$(planned)" \
  && ok "the plan said it too, with origin's name of the branch" || no "plan line for the branch of origin: $(planned | grep 'journal:')"

# --- the journal survives a cut-off write and a damaged line.
# A batch of steps (journal_reach) and a single line are appended with one write, after a newline when the journal does not end in one: a line is
# never joined to the end of another. A line that is not JSON is skipped by every reader, which says so once on stderr, and the others still count.
ROOT=${DA%/bin/qargi}
# jl ARGS: journal_line as a verb of the lead calls it (the steps of a batch on standard input)
jl() { bash -c '. "$1/lib/lib.sh"; . "$1/lib/gitflow.sh"; shift; journal_line "$@"' jl "$ROOT" "$@"; }
h1=$(printf '1%.0s' $(seq 1 40)); h2=$(printf '2%.0s' $(seq 1 40)); h3=$(printf '3%.0s' $(seq 1 40)); h4=$(printf '4%.0s' $(seq 1 40)); h5=$(printf '5%.0s' $(seq 1 40))
# nonl: the journal without the newline that ends its last line, as a write that was cut off leaves it
nonl() { printf '%s' "$(cat "$J")" > "$J.new" && mv "$J.new" "$J"; [ -n "$(tail -c 1 "$J")" ]; }
n=$(jn); nonl || no "(setup) the journal still ends in a newline"
printf '%s\n' "$h1 $h2" "$h2 $h3" "$h3 $h4" | jl "$A" refs/heads/agent/atom - '' test:batch '' 2>"$T/err"
[ "$(jq -s length "$J" 2>&1)" = $((n + 3)) ] && [ "$(wc -l < "$J")" = $((n + 3)) ] && [ -z "$(tail -c 1 "$J")" ] && [ ! -s "$T/err" ] \
  && ok "a batch of steps appended to a journal that does not end in a newline starts a line of its own: every line is JSON, three new ones, nothing said" || no "batch after a missing newline: $(jq -s length "$J" 2>&1), lines $(wc -l < "$J") (expected $((n + 3))): $(cat "$T/err")"
jq -c 'select(.ref == "refs/heads/agent/atom") | [.old[0:1], .new[0:1], .verb]' "$J" | tr -d '\n' | grep -qxF '["1","2","test:batch"]["2","3","test:batch"]["3","4","test:batch"]' \
  && ok "the three steps are there in order, each its own line" || no "the steps of the batch: $(tail -n 3 "$J")"
nonl || no "(setup) the journal still ends in a newline"
jl "$A" refs/heads/agent/atom "$h4" "$h5" test:single '' 2>"$T/err"
[ "$(jq -s length "$J" 2>&1)" = $((n + 4)) ] && [ -z "$(tail -c 1 "$J")" ] && [ ! -s "$T/err" ] \
  && ok "and so is a single line" || no "single line after a missing newline: $(jq -s length "$J" 2>&1): $(cat "$T/err")"
# a batch whose lines cannot all be built writes none of them (jq fails after its first line: the shim stands for any failure part way)
mkdir -p "$T/jqx"; printf '#!/bin/sh\n%s "$@" | head -n 1\nexit 5\n' "$(command -v jq)" > "$T/jqx/jq"; chmod +x "$T/jqx/jq"
sz=$(wc -c < "$J")
printf '%s\n' "$h1 $h2" "$h2 $h3" "$h3 $h4" | PATH=$T/jqx:$PATH jl "$A" refs/heads/agent/atom - '' test:batch '' 2>"$T/err"
[ "$(wc -c < "$J")" = "$sz" ] && grep -q "warning: the ref journal could not be written for refs/heads/agent/atom (test:batch)" "$T/err" \
  && ok "a batch that fails part way adds no line to the journal: a warning, the journal as it was" || no "failed batch: size $sz -> $(wc -c < "$J"): $(cat "$T/err")"
# the batch reaches the journal by one write: python3 is run through a shim that counts the calls of os.write (strace is not on every host; the shim
# sees the same calls, each one write(2)) and logs "WRITTEN/ASKED" for each. bash's printf would hand a batch this size over in blocks of 4 KB.
mkdir -p "$T/pyx"; realpy=$(command -v python3)
printf '#!/bin/sh\nexec %s "%s/pyx/count.py" "$@"\n' "$realpy" "$T" > "$T/pyx/python3"; chmod +x "$T/pyx/python3"
cat > "$T/pyx/count.py" <<'PY'
import os, sys
real, calls = os.write, []
def counting(fd, data):
    # QARGI_TEST_SHORT: the first write takes only that many bytes, as a write cut short by a signal does
    cut = int(os.environ.get("QARGI_TEST_SHORT", "0"))
    n = real(fd, data[:cut] if cut and not calls else data)
    calls.append("%d/%d" % (n, len(data)))
    return n
os.write = counting
code, sys.argv = sys.argv[3], ["-c"] + sys.argv[4:]   # run as: python3 -I -c CODE ARGS
try:
    exec(compile(code, "-c", "exec"), {"__name__": "__main__"})
finally:
    with open(os.environ["QARGI_TEST_WRITES"], "a") as f:
        f.write(" ".join(calls) + "\n")
PY
export QARGI_TEST_WRITES=$T/writes
seq 1 500 | awk -v a="$h1" -v b="$h2" '{print a " " b}' > "$T/steps500"
n=$(jn); sz=$(wc -c < "$J"); : > "$T/writes"
PATH=$T/pyx:$PATH jl "$A" refs/heads/agent/atom - '' test:big '' < "$T/steps500" 2>"$T/err"
grown=$(($(wc -c < "$J") - sz))
[ "$(jn)" = $((n + 500)) ] && [ "$(jq -s length "$J" 2>&1)" = $((n + 500)) ] && [ "$grown" -gt 65536 ] && [ ! -s "$T/err" ] \
  && ok "a batch of 500 lines ($grown bytes, over sixteen blocks of 4 KB) is added whole, every line JSON" || no "batch of 500: lines $(jn) of $((n + 500)), $grown bytes: $(cat "$T/err")"
[ "$(cat "$T/writes")" = "$grown/$grown" ] \
  && ok "and by one write of all of it: os.write was called once, asked for $grown bytes and took them (a bash printf makes one write for each 4 KB)" || no "writes of the batch: $(cat "$T/writes") (expected $grown/$grown)"
: > "$T/writes"; sz=$(wc -c < "$J")
PATH=$T/pyx:$PATH jl "$A" refs/heads/agent/atom "$h4" "$h5" test:one '' 2>"$T/err"
[ "$(cat "$T/writes")" = "$(($(wc -c < "$J") - sz))/$(($(wc -c < "$J") - sz))" ] && ok "a single line is one write too" || no "writes of a single line: $(cat "$T/writes")"
# a write that takes part of the buffer is continued with the rest: nothing is lost or doubled
n=$(jn); : > "$T/writes"
QARGI_TEST_SHORT=100 PATH=$T/pyx:$PATH jl "$A" refs/heads/agent/atom - '' test:short '' < "$T/steps500" 2>"$T/err"
[ "$(jn)" = $((n + 500)) ] && [ "$(jq -s length "$J" 2>&1)" = $((n + 500)) ] && [ "$(awk '{print NF}' "$T/writes")" = 2 ] && [ "$(cut -d' ' -f1 "$T/writes" | cut -d/ -f1)" = 100 ] \
  && ok "a short write (the first took 100 bytes) is followed by a second for the rest: all 500 lines, each once" || no "short write: lines $(jn) of $((n + 500)), writes $(cat "$T/writes"): $(cat "$T/err")"
unset QARGI_TEST_WRITES
cmp -s <(sed -n '/^journal_warn_bad()/,/^}/p' "$ROOT/lib/gitflow.sh") <(sed -n '/^journal_warn_bad()/,/^}/p' "$ROOT/lib/local.sh") && [ -n "$(sed -n '/^journal_warn_bad()/,/^}/p' "$ROOT/lib/local.sh")" ] \
  && ok "journal_warn_bad is the same text in lib/gitflow.sh and lib/local.sh" || no "journal_warn_bad differs between lib/gitflow.sh and lib/local.sh"

# a line that is not JSON in the middle of the journal: verify, ref note and merged.py read the others; the plan and the steps of a deleting verb
# (journal_reach_scan) write nothing from a journal with such a line, since the line may be the one that bounds the branch's life
RC=$(mkrun corrupt-run); $F start cj >/dev/null 2>&1; task agent/cj cj.txt one; $DA ref note agent/cj >/dev/null 2>&1 || no "(setup) note agent/cj"
x0=$(sha agent/cj); RD=$(mkrun corrupt-run-d)   # RD has agent/cj at the commit the lead noted
$F merge cj agent/cj >/dev/null 2>&1 || no "(setup) merge agent/cj into feature/cj"
last=$(tail -n 1 "$J"); head -n -1 "$J" > "$J.new"; printf '%s\n' '{"at":"2026-11-17T10:00:00Z","epoch":17' >> "$J.new"; printf '%s\n' "$last" >> "$J.new"; mv "$J.new" "$J"   # a line cut off in the middle
n=$(jn)
out=$(verify "$RC"); rc=$?
[ $rc = 0 ] && grep -q "feature/cj created by qargi feature start" <<<"$out" && ok "verify reads the journal past a line that is not JSON: the run passes and the change is named" || no "verify with a damaged line: rc=$rc $out"
[ "$(grep -c "1 line of the ref journal .* is not JSON" <<<"$out")" = 1 ] && ok "and it says so once on stderr: one line, which line is meant is for the lead to find (the journal named)" || no "the warning of verify: $(grep -c 'of the ref journal' <<<"$out") times: $(grep 'ref journal' <<<"$out")"
byhand agent/cj y.txt; y0=$(sha agent/cj)
out=$($DA ref note agent/cj 2>&1)
[ "$(sha agent/cj)" = "$y0" ] && grep -q "^noted agent/cj: ${x0:0:12} to ${y0:0:12} (after your earlier note)" <<<"$out" && [ "$(grep -c "of the ref journal .* is not JSON" <<<"$out")" = 1 ] \
  && ok "ref note finds its own earlier note past the damaged line (it continues from it) and says so once" || no "ref note with a damaged line: $out"
byhand agent/cj z.txt; z0=$(sha agent/cj)
$F merge cj agent/cj >/dev/null 2>&1 || no "(setup) merge agent/cj again"
jc=$(jn); out=$(approve $DA branch prune) || no "(setup) prune agent/cj: $out"
# the steps of a deleting verb fail closed: the skipped line may be the creation or the deletion that bounds the branch's life, so with a line
# that cannot be read no step is written (the deletion itself goes on, from the tip, as it does for a branch the journal never had)
cwhy="the ref journal has a line that is not JSON, which may be the creation or the deletion of a branch of this name, so the lines that can be read are not enough to say where it was; remove or repair that line"
cwill="qargi local verify will refuse a run prepared earlier"
[ "$(sha agent/cj)" = "$Z" ] && ! reach agent/cj "$y0" "$z0" branch:prune && [ "$(jn)" = $((jc + 1)) ] && jhas agent/cj "$z0" "$Z" \
  && ok "branch prune with a damaged line in the journal deletes the branch and journals only the deletion: no step from the commit made with git is written" || no "prune with a damaged line: $(grep 'agent/cj' "$J" | tail -n 3)"
grep -qxF "    journal: no step will be journaled for agent/cj: the journal does not lead to ${z0:0:7} ($cwhy): $cwill, while agent/cj was at another commit" <<<"$(planned)" && ! grep -q "journal: takes" <<<"$(planned)" \
  && ok "the plan said so before the approval: no step will be journaled, because of the line that is not JSON" || no "plan with a damaged line: $(planned | grep 'journal:')"
[ "$(grep -c "^note: the journal does not lead to ${z0:0:7}, where agent/cj was deleted ($cwhy): $cwill, while agent/cj was at another commit\$" <<<"$out")" = 1 ] \
  && ok "and the prune printed the note once, with the same reason" || no "note of the prune with a damaged line: $(grep 'agent/cj' <<<"$out")"
[ "$(grep -c "of the ref journal .* is not JSON" <<<"$(planned)")" = 1 ] && [ "$(grep -c "of the ref journal .* is not JSON" <<<"$out")" = 1 ] \
  && ok "each of the plan and the prune says once that a line is skipped" || no "the warnings of the plan and of the prune: $(grep 'ref journal' <<<"$(planned)$out")"
out=$(verify "$RD"); rc=$?
[ $rc != 0 ] && grep -qF "not in the lead's ref journal" <<<"$out" \
  && ok "a run prepared at the noted commit is refused after the prune, as the note said: the journal does not lead from it to the deleted tip" || no "verify of the run at the noted commit: rc=$rc $out"
# merged.py: a run's applied tip is merged when a commit the lead rewrote it to is; a damaged line neither hides the rewrite nor goes unsaid
mkdir -p "$T/ms"; hc=$(hand develop); dv=$(sha develop)
{ printf '%s\n' 'not json at all'; jq -nc --arg r "$(readlink -f "$A")" --arg o "$hc" --arg n "$dv" '{verb:"ref:rewrite", repo:$r, ref:"refs/heads/agent/m", old:$o, new:$n}'; printf '%s' '{"verb":"review:apply","re'; } > "$T/ms/ref-journal.jsonl"
out=$(python3 -I "$ROOT/lib/merged.py" "$A" "$hc" --state "$T/ms" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(grep -c "^qargi: warning: 2 lines of the ref journal $T/ms/ref-journal.jsonl are not JSON" <<<"$out")" = 1 ] && [ "$(wc -l <<<"$out")" = 1 ] \
  && ok "merged.py follows a recorded rewrite past damaged lines (one cut off at the end) and warns once, naming how many" || no "merged.py with damaged lines: rc=$rc $out"
mkdir -p "$T/ms2"; jq -nc --arg r "$(readlink -f "$A")" --arg o "$hc" --arg n "$dv" '{verb:"ref:rewrite", repo:$r, ref:"refs/heads/agent/m", old:$o, new:$n}' > "$T/ms2/ref-journal.jsonl"
out=$(python3 -I "$ROOT/lib/merged.py" "$A" "$hc" --state "$T/ms2" 2>&1); rc=$?
[ $rc = 0 ] && [ -z "$out" ] && ok "and says nothing about a journal whose every line is JSON" || no "merged.py with a clean journal: rc=$rc $out"

# --- the guard protects the journal from a member; reading stays allowed
RG=$(mkrun guard-run); cd "$RG/clone" || exit 1
g() { # tool, json input -> exit status of the guard run in the clone, as a member would
  jq -nc --arg t "$1" --argjson i "$2" --arg c "$RG/clone" '{tool_name:$t, tool_input:$i, cwd:$c}' | "$DA" __guard 2>"$T/guard.err" >/dev/null; }
for spec in "Write|$(jq -nc --arg p "$J" '{file_path:$p, content:"x"}')" "Edit|$(jq -nc --arg p "$J" '{file_path:$p, old_string:"a", new_string:"b"}')" \
            "Bash|$(jq -nc --arg c "echo '{}' >> $J" '{command:$c}')" "Bash|$(jq -nc --arg c "sed -i s/a/b/ $J" '{command:$c}')" \
            "Bash|$(jq -nc --arg c "cat x | tee $J" '{command:$c}')" "Bash|$(jq -nc --arg c "rm -f $J" '{command:$c}')" "Bash|$(jq -nc --arg c "cp x $J" '{command:$c}')" \
            "Bash|$(jq -nc --arg c "head -n 0 $J > $J.new && mv $J.new $J" '{command:$c}')"; do
  g "${spec%%|*}" "${spec#*|}"; rc=$?
  [ $rc = 2 ] && ok "the guard refuses a member's ${spec%%|*} to the journal (${spec#*|})" || no "guard let through ${spec%%|*} ${spec#*|} (rc=$rc)"
done
for spec in "Read|$(jq -nc --arg p "$J" '{file_path:$p}')" "Bash|$(jq -nc --arg c "cat $J" '{command:$c}')" "Bash|$(jq -nc --arg c "grep -c agent $J" '{command:$c}')" \
            "Bash|$(jq -nc --arg c "jq . $J > $RG/out/copy.json" '{command:$c}')"; do
  g "${spec%%|*}" "${spec#*|}"; rc=$?
  [ $rc = 0 ] && ok "the guard lets a member read the journal (${spec#*|})" || no "guard refused a read ${spec#*|} (rc=$rc): $(cat "$T/guard.err")"
done
cd "$OLDPWD" || exit 1
rm -rf "$T"
exit $fail
