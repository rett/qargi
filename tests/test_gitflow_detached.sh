#!/usr/bin/env bash
# Detached long-lived branches (answers repo.detached) on a throwaway repository with a bare origin: no merge between such a
# branch and the git-flow branches, in either direction; tasks cut from it merge into it with a plan and a token.
# Run: tests/test_gitflow_detached.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app QARGI_RUN_TMP=$T
mkdir -p "$HOME" "$T/c/projects"
R=$T/app; git init -q -b master "$R"; git init -q --bare "$T/origin.git"
echo base > "$R/f.txt"; git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$T/origin.git"
# the documentation branch shares no history with the others
git -C "$R" checkout -q --orphan docs-site && git -C "$R" rm -q -rf . && echo "docs home" > "$R/index.md" && git -C "$R" add -A && git -C "$R" commit -q -m "docs"
git -C "$R" push -q origin master develop docs-site
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop","docs-site"], detached:["docs-site"]}, roles:{build:{base:"@dispatcher",push:{mode:"none"}, effort:"medium"}}, models:{provider:{local:"claude-code",cloud:"claude-platform"}}, budget_cents:500, memory:{}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
task() { # name base file: agent/NAME cut from BASE with one commit adding FILE
  git -C "$R" branch "agent/$1" "$2"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$3"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
$DA project validate app >/dev/null 2>&1 && ok "the answers with repo.detached validate" || no "validate: $($DA project validate app 2>&1)"

# --- the name has no feature flow
for v in "start docs-site" "sync docs-site" "verify docs-site" "finish docs-site" "status docs-site"; do
  out=$($F $v 2>&1) && no "feature $v accepted a detached branch" || { grep -q "detached long-lived branch" <<<"$out" && ok "feature $v refuses the detached branch" || no "feature $v message: $out"; }
done
git -C "$R" rev-parse -q --verify refs/heads/feature/docs-site >/dev/null && no "a feature of the detached name exists" || ok "and no feature branch was made"

# --- a task cut from the detached branch merges into it, with a plan and token, locally only
task d1 docs-site page.md
d0=$(git -C "$R" rev-parse docs-site); dev0=$(git -C "$R" rev-parse develop); o0=$(git -C "$T/origin.git" rev-parse docs-site)
out=$($F merge docs-site agent/d1 2>&1); t=$(tok <<<"$out")
[ -n "$t" ] && grep -q "brings 1 commit(s) into docs-site" <<<"$out" && [ "$(git -C "$R" rev-parse docs-site)" = "$d0" ] && ok "the merge into a detached branch prints a plan and changes nothing" || no "plan: $out"
$F merge docs-site agent/d1 --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong plan token is refused"
out=$(QARGI_NESTED=1 $F merge docs-site agent/d1 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ "$(git -C "$R" rev-parse docs-site)" = "$d0" ] && ok "merge into a detached branch with no token under QARGI_NESTED is refused, the branch did not move" || no "nested merge, no token: rc=$rc $out"
out=$(QARGI_NESTED=1 $F merge docs-site agent/d1 --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ "$(git -C "$R" rev-parse docs-site)" = "$d0" ] && ok "and a wrong token is refused under QARGI_NESTED too" || no "nested merge, wrong token: rc=$rc $out"
out=$($F merge docs-site agent/d1 --plan "$t" --approved "go ahead" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-list --parents -n1 docs-site | wc -w)" = 3 ] && git -C "$R" show docs-site:page.md >/dev/null && ok "with the token it merges the task with --no-ff" || no "apply rc=$rc: $out"
[ "$(git -C "$R" rev-parse develop)" = "$dev0" ] && [ "$(git -C "$T/origin.git" rev-parse docs-site)" = "$o0" ] && [ "$(git -C "$R" branch --show-current)" = parked ] && ok "develop, origin and the main checkout are untouched" || no "touched"
$F merge docs-site agent/d1 >/dev/null 2>&1 && no "a merged task was offered again" || ok "a task already in the branch is refused"

# --- the other direction, and everything that would join them
task fromdev develop x.txt
out=$($F merge docs-site agent/fromdev 2>&1) && no "a task cut from develop went into the detached branch" || { grep -q "would bring in history of develop" <<<"$out" && ok "a task cut from develop is refused as a merge into the detached branch" || no "message: $out"; }
out=$($F merge docs-site develop 2>&1) && no "develop went into the detached branch" || ok "develop cannot be merged into it (only agent/* branches)"
$F start theme >/dev/null 2>&1; task dd docs-site more.md
out=$($F merge theme docs-site 2>&1) && no "the detached branch went into a feature" || { grep -q "detached branch" <<<"$out" && ok "the detached branch cannot be merged into a feature" || no "message: $out"; }
out=$($F merge theme agent/dd 2>&1) && no "a task cut from the detached branch went into a feature" || { grep -q "would bring in history of docs-site" <<<"$out" && ok "nor a task cut from it, by history" || no "message: $out"; }
[ "$(git -C "$R" rev-parse feature/theme)" = "$dev0" ] && ok "and the feature did not move" || no "feature moved"
task ok1 develop y.txt
$F merge theme agent/ok1 >/dev/null 2>&1 && ok "an ordinary task still merges into the feature" || no "ordinary merge: $($F merge theme agent/ok1 2>&1)"

# --- a feature that already holds detached history cannot finish
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" feature/theme
git -C "$w" merge -q --allow-unrelated-histories --no-edit docs-site >/dev/null 2>&1 || git -C "$w" merge --abort >/dev/null 2>&1
git -C "$R" worktree remove --force "$w"
git -C "$R" merge-base --is-ancestor docs-site feature/theme && ok "(setup) the feature holds the detached history by a manual merge" || no "setup merge"
$F verify theme >/dev/null 2>&1
out=$($F finish theme 2>&1) && no "finish planned a merge of detached history into develop" || { grep -q "would bring in history of docs-site" <<<"$out" && ok "feature finish refuses it before any plan" || no "finish message: $out"; }
[ "$(git -C "$R" rev-parse develop)" = "$dev0" ] && ok "develop did not move" || no "develop moved"

# --- a release branch that holds detached history cannot finish (the check runs before any plan)
git -C "$R" branch release/0.9.0 develop
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" release/0.9.0
git -C "$w" merge -q --allow-unrelated-histories --no-edit docs-site >/dev/null 2>&1 || git -C "$w" merge --abort >/dev/null 2>&1
git -C "$R" worktree remove --force "$w"
git -C "$R" merge-base --is-ancestor docs-site release/0.9.0 && ok "(setup) the release branch holds the detached history by a manual merge" || no "setup release merge"
m0=$(git -C "$R" rev-parse master); tags0=$(git -C "$R" tag | wc -l)
out=$($DA release finish 0.9.0 2>&1) && no "release finish planned a merge of detached history into master" || { grep -q "would bring in history of docs-site" <<<"$out" && ok "release finish refuses detached history before any plan" || no "release finish message: $out"; }
! grep -q "plan token" <<<"$out" && [ "$(git -C "$R" rev-parse master)" = "$m0" ] && [ "$(git -C "$R" rev-parse develop)" = "$dev0" ] && [ "$(git -C "$R" tag | wc -l)" = "$tags0" ] && ok "no token was offered; master, develop and the tags did not move" || no "release finish changed something: $out"

# --- tasks may be based on the detached branch
out=$($DA local prepare --repo "$R" --base docs-site --slug page --scratch "$T" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^BASE_SHA=$(git -C "$R" rev-parse docs-site)" <<<"$out" && ok "local prepare accepts the detached branch as the base" || no "prepare rc=$rc: $out"

# --- a run based on the detached branch: review apply puts agent/SLUG at the branch's head, and feature merge takes it into the branch
out=$($DA local prepare --repo "$R" --base docs-site --slug guide --scratch "$T" 2>&1); r=$(sed -n 's/^RUN=//p' <<<"$out"); c=$r/clone
b=$(git -C "$c" rev-parse HEAD); ds=$(git -C "$R" rev-parse docs-site)
( cd "$c" || exit 1; export GIT_AUTHOR_NAME=agent GIT_AUTHOR_EMAIL=agent@example.invalid GIT_COMMITTER_NAME=agent GIT_COMMITTER_EMAIL=agent@example.invalid
  echo "how to build the site" > guide.md; git add -A; git commit -q -m "docs: add the guide page" -m "The guide says how the site is built, because the home page only links to it."
  mkdir -p "$r/out/patches"; git format-patch -q -o "$r/out/patches" "$b..HEAD"
  git log --reverse --format='%H%x09%s' "$b..HEAD" | jq -R -s -c '[split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})), patch_groups:[{name:"guide", why:"one change", commits:($c|map(.sha))}]}' > "$r/out/manifest.json"
  echo "# series" > "$r/out/series.md" )
out=$($DA review apply "$r" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-parse agent/guide~1)" = "$ds" ] && ok "review apply of a run based on the detached branch makes agent/guide on that branch's head" || no "apply rc=$rc: $out"
grep -q "feature merge NAME agent/guide" <<<"$out" && ok "and prints the next commands" || no "apply output: $out"
dev1=$(git -C "$R" rev-parse develop); o1=$(git -C "$T/origin.git" rev-parse docs-site)
out=$($F merge docs-site agent/guide 2>&1); t=$(tok <<<"$out")
[ -n "$t" ] && grep -q "brings 1 commit(s) into docs-site" <<<"$out" && [ "$(git -C "$R" rev-parse docs-site)" = "$ds" ] && ok "feature merge DETACHED agent/guide prints a plan and changes nothing" || no "merge plan: $out"
out=$($F merge docs-site agent/guide --plan "$t" --approved "take the guide" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-list --parents -n1 docs-site | wc -w)" = 3 ] && git -C "$R" show docs-site:guide.md >/dev/null && [ "$(git -C "$R" rev-parse develop)" = "$dev1" ] && [ "$(git -C "$T/origin.git" rev-parse docs-site)" = "$o1" ] \
  && ok "with the token it merges the applied task into the detached branch with --no-ff, locally only" || no "merge rc=$rc: $out"
$DA local verify "$r" >/dev/null 2>&1 && ok "and local verify still accepts the run" || no "verify: $($DA local verify "$r" 2>&1)"
out=$($DA local clean "$r" 2>&1); rc=$?
[ $rc = 0 ] && [ ! -e "$r" ] && ok "and local clean removes the run" || no "clean rc=$rc: $out"
rm -rf "$T"
exit $fail
