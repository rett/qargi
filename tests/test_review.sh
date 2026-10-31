#!/usr/bin/env bash
# `qargi review check`: a series of change-specific patches passes; monolithic or unexplained
# ones do not. Run: tests/test_review.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
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
exit $fail
