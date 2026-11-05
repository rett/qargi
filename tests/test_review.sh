#!/usr/bin/env bash
# `qargi review check`: a series of change-specific patches passes; monolithic or unexplained
# ones do not. Run: tests/test_review.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0; DA=$PWD/bin/qargi
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
# the patches are OUT/patches/*.patch, the one place apply reads: loose patches in OUT are not a series; an unknown option is an error, not ignored
mkdir -p "$T/flat"; cp "$T/good/patches/"*.patch "$T/flat/"; cp "$T/good/manifest.json" "$T/flat/"
out=$($DA review check "$T/flat" 2>&1); [ $? = 1 ] && echo "$out" | grep -q "no patches found" && ok "patches loose in OUT (not in OUT/patches) are not accepted" || no "flat patches: $out"
out=$($DA review check "$T/good" --alow-empty 2>&1); rc=$?; [ $rc = 2 ] && echo "$out" | grep -q "unknown option --alow-empty" && ok "a misspelled option is an error" || no "unknown option: rc=$rc $out"
out=$($DA review check "$T/good" "$T/flat" 2>&1); rc=$?; [ $rc = 2 ] && ok "two directories are an error" || no "two args: rc=$rc $out"
# a review run returns a report instead of patches
mkdir -p "$T/rep"; out=$($DA review check "$T/rep" 2>&1); [ $? = 1 ] && ok "a run with neither patches nor a report is refused" || no "empty run: $out"
printf '# Review\n\n## Findings\n\nnone\n' > "$T/rep/report.md"
out=$($DA review check "$T/rep" 2>&1); [ $? = 0 ] && echo "$out" | grep -q "report-only" && ok "a report with a Findings section passes as a review run" || no "report run: $out"
printf '# Review\n\nlooks fine\n' > "$T/rep/report.md"
$DA review check "$T/rep" >/dev/null 2>&1; [ $? = 1 ] && ok "a report without a Findings section is refused" || no "report without findings"
# in a team run every file in OUT starts with the member's prefix: review--report.md is the report
rm -f "$T/rep/report.md"; printf '# Review\n\n## Findings\n\nnone\n' > "$T/rep/review--report.md"
out=$($DA review check "$T/rep" 2>&1); [ $? = 0 ] && echo "$out" | grep -q "report-only.*review--report.md" && ok "a report with an OUT_PREFIX (review--report.md) passes as a review run" || no "prefixed report: $out"
printf '# Review\n\nlooks fine\n' > "$T/rep/review--report.md"
$DA review check "$T/rep" >/dev/null 2>&1; [ $? = 1 ] && ok "a prefixed report without a Findings section is refused" || no "prefixed report without findings"
rm -f "$T/rep/review--report.md"
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
# the run is found in the registry by its real path (the help's own example is `qargi review apply ./run`), and its repository is the registry's
git -C "$A" commit -q --allow-empty -m "moved on"   # the checked-out branch is no longer the run's base
R6=$(newrun rel)
out=$(cd "$T/scr" && $DA review apply "./$(basename "$R6")/" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$A" rev-list --count "$dev..agent/rel")" = 2 ] && ok "a relative run path with a trailing slash finds the run's slug and base in the registry" || no "relative apply: rc=$rc $out"
R7=$(newrun forgedrepo); other=$T/other; git init -q -b master "$other"; echo "$other" > "$R7/repo.path"
out=$($DA review apply "$R7" 2>&1); rc=$?
[ $rc != 0 ] && echo "$out" | grep -q "registry" && ! git -C "$A" rev-parse -q --verify agent/forgedrepo >/dev/null && ok "a run whose repo.path differs from the registry's is refused and creates no branch" || no "forged repo.path: rc=$rc $out"
# what apply records in the run directory (applied, the new snapshot) is not written through a link a member planted there
R8=$(newrun linknew); ln -s "$T/victim8" "$R8/refs.before.new"
out=$($DA review apply "$R8" 2>&1); rc=$?
{ [ $rc = 0 ] && [ ! -e "$T/victim8" ] && grep -q "^local refs/heads/agent/linknew " "$R8/refs.before" && [ ! -L "$R8/refs.before" ] && [ -f "$R8/applied" ] && [ ! -L "$R8/applied" ]; } \
  && ok "a refs.before.new that is a link is not written through: the snapshot is replaced by a rename from the lead's state directory" || no "link refs.before.new: rc=$rc $out"
$DA local verify "$R8" >/dev/null 2>&1 && ok "and verify still accepts the run" || no "verify after apply"
R9=$(newrun linkapplied); ln -s "$T/victim9" "$R9/applied"
out=$($DA review apply "$R9" 2>&1); rc=$?
{ [ $rc != 0 ] && [ ! -e "$T/victim9" ] && ! git -C "$A" rev-parse -q --verify agent/linkapplied >/dev/null && grep -q "applied" <<<"$out"; } \
  && ok "an applied that is a (dangling) link refuses the apply before any branch is made" || no "link applied: rc=$rc $out"
# a patch file name with a space in it (a member names its files) is one patch, not two words
R10=$(newrun spacey); mv "$R10"/out/patches/0001-*.patch "$R10/out/patches/0001-has a space.patch"; mv "$R10"/out/patches/0002-*.patch "$R10/out/patches/0002-it's  here.patch"
out=$($DA review apply "$R10" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(git -C "$A" rev-list --count "$dev..agent/spacey")" = 2 ] && echo "$out" | grep -q "applied 2 patch(es)"; } && ok "patch files whose names hold spaces are applied, as two patches" || no "spacey names: rc=$rc $out"
# --- review prune is gone (qargi branch prune replaces it): the verb and the --yes option are unknown, and no branch is touched
git -C "$A" branch agent/merged-dev develop
h1=$(heads)
out=$($DA review prune 2>&1); rc=$?
[ $rc != 0 ] && [ "$(heads)" = "$h1" ] && ok "review prune is not a verb any more (usage, nothing changes)" || no "review prune: rc=$rc $out"
out=$($DA review prune --yes 2>&1); rc=$?
[ $rc != 0 ] && [ "$(heads)" = "$h1" ] && ok "and --yes deletes nothing" || no "review prune --yes: rc=$rc $out"
out=$($DA review apply --yes "$T/nosuchrun" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "unknown option --yes" <<<"$out" && ok "review apply has no --yes" || no "review apply --yes: rc=$rc $out"
# --- review apply --from-saved ID: the copy a passing verify saved, for a run whose directory is gone (a reboot that emptied a tmpfs)
RS=$(newrun saved1); IS=$(basename "$RS"); SS=$T/s/runs/$IS
$DA local verify "$RS" >/dev/null 2>&1 && [ -d "$SS/out/patches" ] || no "(setup) verify saved no copy of $RS"
out=$($DA review apply --from-saved "$IS" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "still exists" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/saved1 >/dev/null && ok "--from-saved is refused while the run directory exists (apply that)" || no "from-saved, dir there: rc=$rc $out"
rm -rf "$RS"
for bad in "--from-saved" "--from-saved ../x" "--from-saved $IS $RS"; do
  # shellcheck disable=SC2086
  out=$($DA review apply $bad 2>&1); rc=$?; [ $rc = 2 ] && ok "review apply $bad is a usage error" || no "usage '$bad': rc=$rc $out"
done
out=$($DA review apply --from-saved qargi.nosuch 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no saved copy" <<<"$out" && ok "an id with no saved copy is refused" || no "no copy: rc=$rc $out"
out=$($DA review apply --from-saved "$IS" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(git -C "$A" rev-list --count "$dev..agent/saved1")" = 2 ] && grep -q "applied 2 patch(es)" <<<"$out" && read -r ab at _ < "$SS/applied" \
  && [ "$ab" = agent/saved1 ] && [ "$at" = "$(git -C "$A" rev-parse agent/saved1)" ] && grep -q "^local refs/heads/agent/saved1 " "$SS/refs.before"; } \
  && ok "--from-saved applies the saved series on agent/<slug> at the run's base and records it in the saved copy" || no "from-saved apply: rc=$rc $out"
out=$($DA review apply --from-saved "$IS" --branch agent/again 2>&1); rc=$?
[ $rc != 0 ] && grep -q "applied already" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/again >/dev/null && ok "and refuses to apply it twice" || no "from-saved twice: rc=$rc $out"
RS2=$(newrun saved2); IS2=$(basename "$RS2"); $DA local verify "$RS2" >/dev/null 2>&1; rm -rf "$RS2"
git -C "$A" tag hand-made-during-run develop
out=$($DA review apply --from-saved "$IS2" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "REFS CHANGED" <<<"$out" && grep -q "hand-made-during-run" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/saved2 >/dev/null \
  && ok "--from-saved runs local verify on the saved snapshot: refs changed since refuses" || no "from-saved, refs changed: rc=$rc $out"
git -C "$A" tag -d hand-made-during-run >/dev/null
RS3=$(newrun saved3); IS3=$(basename "$RS3"); $DA local verify "$RS3" >/dev/null 2>&1; rm -rf "$RS3"; sed -i 's/^ a$/ zzz/' "$T/s/runs/$IS3"/out/patches/0002-*.patch
rm -f "$T/s/runs/$IS3/out/manifest.json"
out=$($DA review apply --from-saved "$IS3" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "review check refuses" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/saved3 >/dev/null && ok "--from-saved runs review check on the saved OUT" || no "from-saved, check: rc=$rc $out"
exit $fail
