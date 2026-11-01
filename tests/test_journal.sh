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
bad=$(jq -c 'select((keys | sort) != ["at","by","epoch","new","old","project","ref","repo","verb"] or (.old|test("^[0-9a-f]{40}$")|not) or (.new|test("^[0-9a-f]{40}$")|not) or (.epoch|type) != "number" or .project != "app" or (.by|length) == 0 or (.verb|length) == 0)' "$J" 2>&1 | head -3)
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

# --- prune journals the deletions
for b in p1 p2; do git -C "$A" branch "agent/$b" develop; done
RP=$(mkrun prune-run); n=$(jn)
$DA review prune >/dev/null 2>&1; [ -f "$J" ] && [ "$(jn)" = "$n" ] && ok "prune without --yes (a listing) journals nothing" || no "prune listing journaled"
pout=$($DA review prune --yes 2>&1); dels=$(grep -c '^deleted ' <<<"$pout")
jhas agent/p1 "$(sha develop)" "$Z" && jhas agent/p2 "$(sha develop)" "$Z" && [ "$(jn)" -ge $((n + 2)) ] && ok "prune --yes journals each deletion (new is all zeros)" || no "prune left no journal lines: $pout"
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
$F finish fin --plan "$t" --approved go >/dev/null 2>&1; rc=$?
d1=$(sha develop)
[ $rc = 0 ] && [ "$d1" != "$d0" ] && jhas develop "$d0" "$d1" && ok "feature finish journals develop's move" || no "finish: rc=$rc, journal $(tail -n +"$((n + 1))" "$J" 2>&1)"
jhas feature/fin "$fin" "$Z" && ok "and the deletion of the feature branch" || no "finish left no deletion line"

# --- a release
$REL verify 0.2.0 >/dev/null 2>&1; d0=$(sha develop)
$REL start 0.2.0 --date 2026-01-02 >/dev/null 2>&1; rb=$(sha release/0.2.0)
jhas release/0.2.0 "$Z" "$rb" && [ "$rb" != "$Z" ] && ok "release start journals the new release branch" || no "release start left no journal line"
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
m0=$(sha master); d0=$(sha develop); t=$($REL finish 0.2.0 | tok)
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
m1=$(sha master); d1=$(sha develop)
[ $rc = 0 ] && [ "$m1" != "$m0" ] && jhas master "$m0" "$m1" && jhas develop "$d0" "$d1" && jhas release/0.2.0 "$rb" "$Z" && ok "release finish journals master, develop and the release branch's deletion" || no "release finish: rc=$rc, lines $(tail -n 4 "$J" 2>&1)"

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
