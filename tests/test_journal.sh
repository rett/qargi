#!/usr/bin/env bash
# The ref-move journal ($QARGI_STATE/ref-journal.jsonl): every local branch creation, move and deletion made by qargi's
# own verbs is recorded, so `qargi local verify` can accept what the lead did since a run's snapshot and still refuse
# anything done by hand, any tag, and any push. Run: tests/test_journal.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
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
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
sha() { git -C "$A" rev-parse -q --verify "$1" 2>/dev/null || echo "$Z"; }
jn() { if [ -f "$J" ]; then wc -l < "$J"; else echo 0; fi; }
# jhas REF-SUFFIX OLD NEW: the journal holds a line for that ref (a branch name ending as given) going from OLD to NEW
jhas() { [ -f "$J" ] && jq -c --arg r "$1" --arg o "$2" --arg n "$3" 'select((.ref | endswith($r)) and .old == $o and .new == $n)' "$J" | grep -q .; }
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
pout=$($DA branch prune --plan "$pt" --approved "prune them" 2>&1); dels=$(grep -c '^deleted ' <<<"$pout")
jhas agent/a "$a0" "$Z" && jhas agent/b "$b0" "$Z" && [ "$(jn)" -ge $((n + 2)) ] && ok "branch prune journals each deletion (new is all zeros)" || no "prune left no journal lines: $pout"
[ "$(jq -c 'select(.new == "0000000000000000000000000000000000000000")' "$J" | tail -n "$dels" | wc -l)" = "$dels" ] && ok "one deletion line per deleted branch" || no "deletion lines vs '$pout'"
out=$(verify "$RP"); [ $? = 0 ] && ok "a run prepared before the prune verifies" || no "verify after prune: $out"

# --- what is still refused: each on a run prepared just before the change, which must verify untouched first
git -C "$A" branch zz develop; git -C "$A" branch agent/gone develop
fresh() { local r; r=$(mkrun "$1"); out=$(verify "$r") || no "(setup) $1 does not verify on an untouched repository: $out"; rm -f "$r/verified"; echo "$r"; }
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
[ $rc = 0 ] && grep -q "feature/fin deleted by qargi feature finish" <<<"$out" && ok "after a passing verify too: the journaled deletion of the feature branch is accepted (fast-forwards alone were before)" || no "verify after finish (lenient): rc=$rc $out"
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
