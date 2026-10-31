#!/usr/bin/env bash
# `qargi review check`: a series of change-specific patches passes; monolithic or unexplained
# ones do not. Run: tests/test_review.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
git init -q -b main "$T/r"; cd "$T/r" || exit 1
git config user.name t; git config user.email t@example.net
mkdir -p internal docs man; echo a > internal/a.go; echo a > docs/a.md; echo a > man/a.1; git add -A; git commit -q -m base; BASE=$(git rev-parse HEAD)
mk() { GIT_AUTHOR_DATE="$3" GIT_COMMITTER_DATE="$3" git commit -q -m "$1" -m "$2"; }
echo b >> internal/a.go; git add -A; mk "names: accept periods" "The pattern now allows single periods between runs, because users such as alice.smith exist." "2026-10-27T10:00:00"
echo b >> docs/a.md; echo b >> man/a.1; git add -A; mk "docs: describe the period rule" "The manual and docs page say what a name may hold." "2026-10-27T10:20:00"
echo c >> internal/a.go; git add -A; mk "rollback: refuse dotted names" "Older releases cannot read them, so the rollback refuses and lists the users." "2026-10-27T10:50:00"
run() { rm -rf "${T:?}/$1"; mkdir -p "$T/$1/patches"; git format-patch -q -o "$T/$1/patches" "$BASE..HEAD"; }
manifest() { # dir with n commits
  git log --reverse --format='%H%x09%s' "$BASE..HEAD" | jq -R -s -c --argjson g "${2:-true}" '
    [split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})),
       patch_groups:(if $g then [{name:"dots", why:"one change", commits:($c|map(.sha))}] else [] end)}' > "$1/manifest.json"; }
run good; manifest "$T/good"; echo "# series" > "$T/good/series.md"
out=$($DA review check "$T/good" 2>&1); rc=$?
[ $rc = 0 ] && ok "a series of change-specific patches with messages passes" || { no "good series: $out"; }
echo "$out" | grep -q "within" && no "a spread-out series was flagged as a batch" || ok "commits made over time are not flagged as a batch"

# one monolithic patch over three areas
git reset -q --soft "$BASE"; mk "all the work" "everything" "2026-10-27T11:00:00"
run mono; manifest "$T/mono"; echo "# s" > "$T/mono/series.md"
out=$($DA review check "$T/mono" 2>&1); [ $? = 1 ] && echo "$out" | grep -q "monolithic" && ok "one patch over several areas is refused as monolithic" || no "monolith: $out"

# a commit without a message body
git reset -q --hard "$BASE"; echo d >> internal/a.go; git add -A; git commit -q -m "bare subject only"
run nobody; manifest "$T/nobody"; echo "# s" > "$T/nobody/series.md"
out=$($DA review check "$T/nobody" 2>&1); [ $? = 1 ] && echo "$out" | grep -q "no body" && ok "a commit without a message body is refused" || no "nobody: $out"

# manifest disagrees with the patches
cp -r "$T/good" "$T/mismatch"; jq '.commits |= .[:2]' "$T/mismatch/manifest.json" > "$T/mismatch/m.json" && mv "$T/mismatch/m.json" "$T/mismatch/manifest.json"
out=$($DA review check "$T/mismatch" 2>&1); [ $? = 1 ] && echo "$out" | grep -q "one patch per commit" && ok "a manifest that does not match the patches is refused" || no "mismatch: $out"

# commits made together at the end are noted
git reset -q --hard "$BASE"
for k in 1 2 3; do echo "$k" >> "internal/f$k.go"; git add -A; mk "step $k" "Why step $k happened." "2026-10-27T12:00:0$k"; done
run batch; manifest "$T/batch"; echo "# s" > "$T/batch/series.md"
$DA review check "$T/batch" 2>&1 | grep -q "NOTE.*batch" && ok "commits made within seconds of each other are noted" || no "batch note"

# missing commit advice / groups are warnings
cp -r "$T/good" "$T/nogroups"; jq 'del(.patch_groups) | del(.commit_advice)' "$T/nogroups/manifest.json" > "$T/nogroups/m.json" && mv "$T/nogroups/m.json" "$T/nogroups/manifest.json"
out=$($DA review check "$T/nogroups" 2>&1); [ $? = 0 ] && echo "$out" | grep -q "patch_groups" && ok "missing patch groups and commit advice are warned about" || no "nogroups: $out"
# a review run returns a report instead of patches
mkdir -p "$T/rep"; out=$($DA review check "$T/rep" 2>&1); [ $? = 1 ] && ok "a run with neither patches nor a report is refused" || no "empty run: $out"
printf '# Review\n\n## Findings\n\nnone\n' > "$T/rep/report.md"
out=$($DA review check "$T/rep" 2>&1); [ $? = 0 ] && echo "$out" | grep -q "report-only" && ok "a report with a Findings section passes as a review run" || no "report run: $out"
printf '# Review\n\nlooks fine\n' > "$T/rep/report.md"
$DA review check "$T/rep" >/dev/null 2>&1; [ $? = 1 ] && ok "a report without a Findings section is refused" || no "report without findings"
# --- qargi review apply: a collected, checked run becomes a task branch of the real repository
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scr"
A=$T/app; git init -q -b master "$A"; git -C "$A" config user.name lead; git -C "$A" config user.email lead@example.net
mkdir -p "$A/internal" "$A/docs" "$A/man"; echo a > "$A/internal/a.go"; echo a > "$A/docs/a.md"; echo a > "$A/man/a.1"
git -C "$A" add -A; git -C "$A" commit -q -m base; git -C "$A" branch develop; git -C "$A" checkout -q -b parked
jq -n --arg p "$A" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
newrun() { # slug -> RUN (prepared, with a two-commit series collected into OUT)
  local out r c b
  out=$($DA local prepare --repo "$A" --base develop --slug "$1" --scratch "$T/scr") || return 1
  r=$(echo "$out" | sed -n 's/^RUN=//p'); c=$r/clone; b=$(git -C "$c" rev-parse HEAD)
  ( cd "$c" || exit 1; export GIT_AUTHOR_NAME=agent GIT_AUTHOR_EMAIL=agent@example.invalid GIT_COMMITTER_NAME=agent GIT_COMMITTER_EMAIL=agent@example.invalid
    echo b >> internal/a.go; git add -A; mk "names: accept periods" "The pattern now allows single periods between runs." "2026-10-27T10:00:00"
    echo b >> docs/a.md; echo b >> man/a.1; git add -A; mk "docs: describe the period rule" "The manual and docs say what a name may hold." "2026-10-27T10:20:00"
    BASE=$b; mkdir -p "$r/out/patches"; git format-patch -q -o "$r/out/patches" "$b..HEAD"; manifest "$r/out"; echo "# series" > "$r/out/series.md" )
  echo "$r"
}
heads() { git -C "$A" for-each-ref --format='%(refname) %(objectname)'; }
dev=$(git -C "$A" rev-parse develop); h0=$(heads)
R1=$(newrun names)
out=$($DA review apply "$R1" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$A" rev-parse agent/names~2)" = "$dev" ] && [ "$(git -C "$A" rev-list --count "$dev..agent/names")" = 2 ] && ok "apply creates agent/<slug> at the run's base with every patch" || no "apply: rc=$rc $out"
echo "$out" | grep -q "names: accept periods" && echo "$out" | grep -q "feature merge NAME agent/names" && echo "$out" | grep -q "local clean" && ok "apply prints the commits and the next commands" || no "apply output: $out"
[ "$(git -C "$A" log -1 --format=%cn agent/names)" = lead ] && ok "the commits carry the repository's committer" || no "committer"
[ "$(heads | grep -v '^refs/heads/agent/names ')" = "$h0" ] && [ "$(git -C "$A" branch --show-current)" = parked ] && [ -z "$(git -C "$A" status --porcelain)" ] && [ "$(git -C "$A" worktree list | wc -l)" = 1 ] \
  && ok "no other ref, the checkout or a worktree was changed" || no "side effects"
read -r ab at _ < "$R1/applied"; [ "$ab" = agent/names ] && [ "$at" = "$(git -C "$A" rev-parse agent/names)" ] && $DA local verify "$R1" >/dev/null 2>&1 && ok "the application is recorded in the run and local verify still accepts it" || no "applied record"
$DA review apply "$R1" >/dev/null 2>&1 && no "a run was applied twice" || ok "a run that was applied is refused"

R2=$(newrun failing); rm -f "$R2/out/manifest.json"
out=$($DA review apply "$R2" 2>&1); rc=$?; [ $rc != 0 ] && echo "$out" | grep -q FAIL && ! git -C "$A" rev-parse -q --verify agent/failing >/dev/null && ok "a failing review check refuses and creates no branch" || no "failing check: $out"

R3=$(newrun pushed); git -C "$A" branch intruder develop
out=$($DA review apply "$R3" 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q "REFS CHANGED" && echo "$out" | grep -q "intruder" && ! git -C "$A" rev-parse -q --verify agent/pushed >/dev/null && ok "refs changed during the run refuses, prints the diff and creates no branch" || no "refs changed: $out"
git -C "$A" branch -q -D intruder

git -C "$A" branch agent/taken develop; R4=$(newrun taken)
out=$($DA review apply "$R4" 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q "exists already" && [ "$(git -C "$A" rev-parse agent/taken)" = "$dev" ] && ok "an existing branch is refused and left alone" || no "existing branch: $out"
$DA review apply "$R4" --branch agent/other >/dev/null 2>&1 && [ "$(git -C "$A" rev-list --count "$dev..agent/other")" = 2 ] && ok "--branch overrides the name" || no "--branch"

R5=$(newrun broken); sed -i 's/^ a$/ zzz/' "$R5"/out/patches/0002-*.patch
out=$($DA review apply "$R5" 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q "0002-" && ! git -C "$A" rev-parse -q --verify agent/broken >/dev/null && [ "$(git -C "$A" worktree list | wc -l)" = 1 ] && [ -z "$(find "$T/s" -maxdepth 1 -name "apply-wt.*")" ] \
  && ok "a patch that does not apply names the patch and leaves no branch or worktree" || no "non-applying: rc=$rc $out"
# --- qargi review prune: only merged agent/* branches, only with --yes
git -C "$A" branch -q -D agent/names agent/other agent/taken 2>/dev/null
git -C "$A" branch agent/merged-dev develop; git -C "$A" branch agent/at-master master
git -C "$A" branch agent/in-feature develop; git -C "$A" branch feature/x develop
git -C "$A" worktree add -q "$T/fw" feature/x; echo f > "$T/fw/f.txt"; git -C "$T/fw" add -A; git -C "$T/fw" commit -q -m "feature work"
git -C "$A" worktree remove --force "$T/fw"
git -C "$A" checkout -q -b agent/unmerged develop; echo u > "$A/u.txt"; git -C "$A" add -A; git -C "$A" commit -q -m "unmerged work"; git -C "$A" checkout -q parked
git -C "$A" branch agent/in-feature2 feature/x
git -C "$A" branch other/merged develop
git -C "$A" worktree add -q "$T/held" -b agent/held develop
h1=$(heads)
out=$($DA review prune 2>&1); rc=$?
[ $rc = 0 ] && [ "$(heads)" = "$h1" ] && echo "$out" | grep -q "agent/merged-dev" && echo "$out" | grep -q "agent/in-feature2" && echo "$out" | grep -q "agent/at-master" && ! echo "$out" | grep -q "agent/unmerged" \
  && ok "prune without --yes lists the merged agent/* branches and changes nothing" || no "prune list: $out"
out=$($DA review prune --yes 2>&1); rc=$?
git -C "$A" rev-parse -q --verify agent/merged-dev >/dev/null && no "a merged branch survived --yes" || ok "prune --yes deletes branches merged into develop"
git -C "$A" rev-parse -q --verify agent/in-feature2 >/dev/null && no "a branch merged into a feature survived" || ok "prune --yes deletes branches merged into a feature/*"
git -C "$A" rev-parse -q --verify agent/unmerged >/dev/null && git -C "$A" rev-parse -q --verify agent/held >/dev/null && git -C "$A" rev-parse -q --verify other/merged >/dev/null && git -C "$A" rev-parse -q --verify feature/x >/dev/null \
  && ok "unmerged, checked-out and non-agent branches are never touched" || no "prune touched another branch: $out"
echo "$out" | grep -q "deleted agent/merged-dev" && ok "prune prints what it deleted" || no "prune output: $out"
exit $fail
