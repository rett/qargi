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
# RUN_DIR instead of OUT: a directory with an out directory is read through its out
mkdir -p "$T/rundir"; cp -r "$T/good" "$T/rundir/out"
out=$($DA review check "$T/rundir" 2>&1); rc=$?; [ $rc = 0 ] && echo "$out" | grep -q "NOTE checked $T/rundir/out" && echo "$out" | grep -q "0 fail" && ok "a run directory is checked as its out directory, with a note" || no "run dir: rc=$rc $out"
cp -r "$T/mono/patches" "$T/rundir/out/patches.bad"; rm -rf "$T/rundir/out/patches"; mv "$T/rundir/out/patches.bad" "$T/rundir/out/patches"; cp "$T/mono/manifest.json" "$T/rundir/out/manifest.json"
$DA review check "$T/rundir" >/dev/null 2>&1; [ $? = 1 ] && ok "a run directory's out directory that fails is refused" || no "run dir with a bad out"
mkdir -p "$T/outwins/out"; cp -r "$T/good/." "$T/outwins/"
out=$($DA review check "$T/outwins" 2>&1); rc=$?; [ $rc = 0 ] && ! echo "$out" | grep -q "NOTE checked" && ok "a directory that holds patches itself is checked as it is, even with a subdirectory named out" || no "out wins: rc=$rc $out"
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
# --- the author of the applied commits: the lead's (answer git.author, else the repository's identity), the member's with review.keep_author or with no identity
AF=$T/c/projects/app.json; AF0=$T/af0.json; cp "$AF" "$AF0"
authors() { git -C "$A" log --format='%an <%ae>' "$dev..$1" | sort -u; }
names_tip=$(git -C "$A" rev-parse agent/names)
# default: no git.author, so the repository's user.name and user.email; the committer, the dates and the message are the patch's; the member is in the journal
R20=$(newrun auth1); ad1=$(git -C "$R20/clone" log -1 --format=%aI HEAD~1)
out=$($DA review apply "$R20" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/auth1)" = "lead <lead@example.net>" ] && [ "$(git -C "$A" log --format=%cn "$dev..agent/auth1" | sort -u)" = lead ] \
  && [ "$(git -C "$A" log --reverse --format=%aI "$dev..agent/auth1" | head -1)" = "$ad1" ] && [ "$(git -C "$A" log -1 --format=%B agent/auth1 | grep -c .)" = 2 ]; } \
  && ok "apply resets the author to the repository's identity (no git.author), keeps the committer, the dates and the message" || no "default reset: rc=$rc $(authors agent/auth1) $out"
grep -q "^author reset to lead <lead@example.net> (the repository's user.name and user.email; no answer git.author); member author recorded in the ref journal: agent <agent@example.invalid>$" <<<"$out" \
  && ok "and says so in its output" || no "reset line: $out"
jq -e -s 'map(select(.verb == "review:apply" and .ref == "refs/heads/agent/auth1")) | length == 1 and (.[0].why | contains("agent <agent@example.invalid>"))' "$T/s/ref-journal.jsonl" >/dev/null \
  && grep -q '"verb":"review:apply".*agent <agent@example.invalid>' "$T/s/audit.log" && ok "the member's author is in the ref journal and the audit log, and not in the commit" || no "journal: $(tail -2 "$T/s/ref-journal.jsonl")"
[ -z "$(git -C "$A" log --format=%B "$dev..agent/auth1" | grep -i 'agent@example.invalid\|co-authored\|signed-off')" ] && ok "no trailer or member name in the commit messages" || no "trailers"
# a commit.cleanup=strip in the repository does not drop the message lines that start with #: the amend that resets the author keeps the message as it is
R26=$(newrun hashmsg)
( cd "$R26/clone" || exit 1; export GIT_AUTHOR_NAME=agent GIT_AUTHOR_EMAIL=agent@example.invalid GIT_COMMITTER_NAME=agent GIT_COMMITTER_EMAIL=agent@example.invalid
  echo d >> internal/a.go; git add -A; git commit -q -m "keep the heading" -m "# Heading line stays
plain line stays"
  BASE=$(git rev-parse origin/develop); rm -f "$R26"/out/patches/*; git format-patch -q -o "$R26/out/patches" "$BASE..HEAD"; manifest "$R26/out" )
git -C "$A" config commit.cleanup strip
out=$($DA review apply "$R26" 2>&1); rc=$?
git -C "$A" config --unset commit.cleanup
{ [ $rc = 0 ] && [ "$(authors agent/hashmsg)" = "lead <lead@example.net>" ] && git -C "$A" log -1 --format=%B agent/hashmsg | grep -qx '# Heading line stays'; } \
  && ok "the author reset keeps a message line that starts with # (commit.cleanup=strip in the repository)" || no "cleanup: rc=$rc $(git -C "$A" log -1 --format=%B agent/hashmsg 2>&1) $out"
# an identity read from the repository is checked as git.author is: no < > or control character
for bad in 'Evil <evil@example.com>' $'Ab\tcd'; do
  git -C "$A" config user.name "$bad"
  R27=$(newrun badid)
  out=$($DA review apply "$R27" 2>&1); rc=$?
  { [ $rc != 0 ] && grep -q "user.name and user.email .* are not a plain 'Name <email>'" <<<"$out" && grep -q "nothing was applied" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/badid >/dev/null && [ "$(git -C "$A" worktree list | wc -l)" = 1 ]; } \
    && ok "a repository user.name that is not a plain name is refused before anything is applied" || no "bad identity: rc=$rc $out"
  $DA local clean "$R27" --discard >/dev/null 2>&1 || rm -rf "$R27"
done
git -C "$A" config user.name lead
# git.author set with project set: it wins over the repository's identity
jq '.git.author = "Example Author <author@example.com>"' "$AF0" > "$AF"   # (project set stores it the same way; tests/test_project.sh covers the verb)
R21=$(newrun auth2)
out=$($DA review apply "$R21" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/auth2)" = "Example Author <author@example.com>" ] && [ "$(git -C "$A" log --format=%cn "$dev..agent/auth2" | sort -u)" = lead ] \
  && grep -q "^author reset to Example Author <author@example.com> (answer git.author); member author recorded in the ref journal: agent <agent@example.invalid>$" <<<"$out"; } \
  && ok "the answer git.author is the author of the applied commits, the committer stays the repository's" || no "git.author: rc=$rc $(authors agent/auth2) $out"
[ "$(git -C "$A" rev-parse agent/names)" = "$names_tip" ] && [ "$(authors agent/names)" = "lead <lead@example.net>" ] && ok "history applied before is not rewritten" || no "old history rewritten"
# the answers are the run's own (the lead's registry holds the copy taken at prepare): an answer changed after prepare, or a decoy project file for the same
# repository, changes neither the author nor keep_author of this run
R25=$(newrun decoy)
jq '.git.author = "Evil Author <evil@example.com>" | .review.keep_author = true' "$AF" > "$T/c/projects/aaa.json"
jq '.git.author = "Late Author <late@example.com>"' "$AF" > "$T/af.late" && mv "$T/af.late" "$AF"
out=$($DA review apply "$R25" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/decoy)" = "Example Author <author@example.com>" ] && grep -q "^author reset to Example Author <author@example.com> (answer git.author)" <<<"$out"; } \
  && ok "a decoy projects/aaa.json and a later change of git.author do not change the author a prepared run gets" || no "decoy author: rc=$rc $(authors agent/decoy) $out"
rm -f "$T/c/projects/aaa.json"; jq '.git.author = "Example Author <author@example.com>"' "$AF0" > "$AF"
# --from-saved uses the same rule
RS4=$(newrun savedauth); IS4=$(basename "$RS4"); $DA local verify "$RS4" >/dev/null 2>&1; rm -rf "$RS4"
out=$($DA review apply --from-saved "$IS4" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/savedauth)" = "Example Author <author@example.com>" ] && grep -q "^author reset to Example Author <author@example.com> (answer git.author)" <<<"$out"; } \
  && ok "--from-saved resets the author the same way" || no "from-saved author: rc=$rc $(authors agent/savedauth) $out"
# review.keep_author true: the member's author stays and the output says so
jq '.review.keep_author = true' "$AF" > "$AF.new" && mv "$AF.new" "$AF"
R22=$(newrun keep)
out=$($DA review apply "$R22" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/keep)" = "agent <agent@example.invalid>" ] && grep -q "^author kept as the member's (answer review.keep_author): agent <agent@example.invalid>$" <<<"$out"; } \
  && ok "review.keep_author true keeps the member's author and says so" || no "keep_author: rc=$rc $(authors agent/keep) $out"
RS5=$(newrun savedkeep); IS5=$(basename "$RS5"); $DA local verify "$RS5" >/dev/null 2>&1; rm -rf "$RS5"
out=$($DA review apply --from-saved "$IS5" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(authors agent/savedkeep)" = "agent <agent@example.invalid>" ]; } && ok "--from-saved keeps the member's author with review.keep_author" || no "from-saved keep: rc=$rc $out"
cp "$AF0" "$AF"
# neither git.author nor a repository identity: the member's author stays, and the output says so
git -C "$A" config --unset user.name; git -C "$A" config --unset user.email
R23=$(newrun noid)
out=$($DA review apply "$R23" 2>&1); rc=$?
git -C "$A" config user.name lead; git -C "$A" config user.email lead@example.net
{ [ $rc = 0 ] && [ "$(authors agent/noid)" = "agent <agent@example.invalid>" ] && grep -q "^author kept as the member's (no answer git.author and no user.name and user.email in the repository): agent <agent@example.invalid>$" <<<"$out"; } \
  && ok "with no git.author and no repository identity the member's author stays and the output says so" || no "no identity: rc=$rc $(authors agent/noid) $out"
# a hand-edited answers file that breaks the answers is refused before anything is applied
for bad in '.git={author:"no email"}' '.git={author:3}' '.review={keep_author:"yes"}' '.review=5'; do
  jq "$bad" "$AF0" > "$AF"; R24=$(newrun badans)
  out=$($DA review apply "$R24" 2>&1); rc=$?
  { [ $rc != 0 ] && grep -q "nothing was applied" <<<"$out" && ! git -C "$A" rev-parse -q --verify agent/badans >/dev/null && [ "$(git -C "$A" worktree list | wc -l)" = 1 ]; } \
    && ok "answers $bad are refused before anything is applied" || no "bad answers $bad: rc=$rc $out"
  $DA local clean "$R24" --discard >/dev/null 2>&1 || rm -rf "$R24"
done
cp "$AF0" "$AF"
# --- the declared take-in scrub: review.scrub (a command run in a temporary checkout of the applied series, with the range in QARGI_SCRUB_BASE and
# QARGI_SCRUB_TIP) and review.trailer_policy reject; both are the run's own copy (taken at prepare); no answer, no change
refs_all() { git -C "$A" for-each-ref --format='%(refname) %(objectname)'; git -C "$A" worktree list; find "$T/s" -maxdepth 1 -name 'scrub-wt.*' | wc -l; }
scrubs() { grep -c '^scrub:' <<<"$1" || true; }
setans() { jq "$1" "$AF0" > "$AF.new" && mv "$AF.new" "$AF"; }   # the stored answers: the original with one change
R30=$(newrun noscrub); out=$($DA review check "$R30/out" 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q '^scrub:' <<<"$out"; } && ok "no review.scrub and no trailer policy: nothing more is checked or printed" || no "no scrub: rc=$rc $out"
R31=$(newrun scrubnone)
# the answer is taken at prepare: this one is set before, a different one after is not believed
SC='test "$QARGI_SCRUB_BASE" = "'$dev'" && test "$(git rev-list --count "$QARGI_SCRUB_BASE..$QARGI_SCRUB_TIP")" = 2 && test "$(git rev-parse HEAD)" = "$QARGI_SCRUB_TIP" && test "$(wc -l < internal/a.go)" = 2 && test "$(git -C "'$A'" rev-parse -q --verify refs/heads/agent/scrubok || echo none)" = none'
jq --arg c "$SC" '.review.scrub = $c' "$AF0" > "$AF.new" && mv "$AF.new" "$AF"
R32=$(newrun scrubok); r0=$(refs_all)
setans '.review.scrub = "echo late scrub; exit 1"'
out=$($DA review check "$R32/out" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(scrubs "$out")" = 1 ] && grep -qx 'scrub: ok' <<<"$out"; } && ok "review.scrub runs in a checkout at the applied series with the range in its environment, and passes: scrub: ok" || no "scrub ok: rc=$rc $out"
out=$($DA review check "$R32" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qx 'scrub: ok' <<<"$out"; } && ok "the scrub runs when the run directory is given instead of OUT" || no "scrub run dir: rc=$rc $out"
[ "$(refs_all)" = "$r0" ] && [ -z "$(git -C "$A" tag)" ] && ok "no ref, worktree or temporary directory is left behind" || no "left behind: $(refs_all)"
# a run that was checked and never applied leaves the scrub record of review check; local clean removes the run and that record with it
sok="$T/s/scrub_ok/${R32##*/}"
[ -f "$sok" ] && ok "a passing scrub leaves its record for the run (scrub_ok/RUN-ID)" || no "no scrub record: $(ls -la "$T/s/scrub_ok" 2>&1)"
out=$($DA local clean "$R32" --discard 2>&1); rc=$?
{ [ $rc = 0 ] && [ ! -e "$R32" ] && [ ! -e "$sok" ]; } && ok "local clean removes the scrub record of a run that was checked and never applied" || no "clean scrub record: rc=$rc $out; record: $(ls "$sok" 2>&1)"
# the registry's copy, not the stored file, decides: a run prepared with no scrub is not scrubbed by a later answer
out=$($DA review check "$R31/out" 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q '^scrub:' <<<"$out"; } && ok "an answer set after prepare does not change the scrub of a run already out" || no "late answer: rc=$rc $out"
# a failing scrub: one FAIL line with its first lines, the check fails
setans '.review.scrub = "echo found a stray debug line; echo second; echo third; echo fourth; exit 3"'
R33=$(newrun scrubfail); r0=$(refs_all)
out=$($DA review check "$R33/out" 2>&1); rc=$?
{ [ $rc = 1 ] && [ "$(scrubs "$out")" = 1 ] && grep -qx 'scrub: FAIL found a stray debug line | second | third' <<<"$out" && grep -q '^0 fail' <<<"$out"; } \
  && ok "a failing scrub prints one 'scrub: FAIL' line with its first lines and fails the check" || no "scrub fail: rc=$rc $out"
[ "$(refs_all)" = "$r0" ] && ok "a failing scrub leaves nothing behind either" || no "left behind after fail: $(refs_all)"
setans '.review.scrub = "exit 4"'; R34=$(newrun scrubsilent)
out=$($DA review check "$R34/out" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -qx 'scrub: FAIL exit 4, no output' <<<"$out"; } && ok "a failing scrub with no output still says why" || no "silent scrub: rc=$rc $out"
# a list of words is run without a shell; the range is in the environment
setans '.review.scrub = ["sh", "-c", "test -n \"$QARGI_SCRUB_BASE\" && test -n \"$QARGI_SCRUB_TIP\" && test \"$0\" = \"a b\"", "a b"]'; R35=$(newrun scrublist)
out=$($DA review check "$R35/out" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qx 'scrub: ok' <<<"$out"; } && ok "review.scrub as a list of words runs too" || no "scrub list: rc=$rc $out"
# a series that fails the check is not scrubbed, and the line says so
setans '.review.scrub = "exit 0"'; R36=$(newrun scrubskip); rm -f "$R36/out/manifest.json"
out=$($DA review check "$R36/out" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -qx 'scrub: not run (the series check failed)' <<<"$out"; } && ok "a series that fails the check is not scrubbed, and the output says so" || no "scrub skip: rc=$rc $out"
# a series that does not apply on the base fails the scrub
R37=$(newrun scrubnoapply); sed -i 's/^ a$/ zzz/' "$R37"/out/patches/0002-*.patch
out=$($DA review check "$R37/out" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q '^scrub: FAIL 0002-.* does not apply on ' <<<"$out"; } && ok "a series that does not apply fails the scrub and names the patch" || no "scrub noapply: rc=$rc $out"
# review.trailer_policy reject: a co-author or generated-with trailer in any commit fails; none (the default) lets it pass
setans '.review.trailer_policy = "reject"'
R38=$(newrun trailok)
out=$($DA review check "$R38/out" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qx 'scrub: ok' <<<"$out"; } && ok "trailer_policy reject passes a series with no such trailer" || no "trailer ok: rc=$rc $out"
for tr in 'Co-Authored-By: Someone <someone@example.net>' 'co-authored-by: Someone <someone@example.net>' 'Generated with Some Tool' 'Generated-with: some tool'; do
  R39=$(newrun trailbad); r0=$(refs_all)
  sed -i "s/^The manual and docs say what a name may hold\.\$/&\n\n$tr/" "$R39"/out/patches/0002-*.patch
  out=$($DA review check "$R39/out" 2>&1); rc=$?
  { [ $rc = 1 ] && [ "$(scrubs "$out")" = 1 ] && grep -q "^scrub: FAIL review.trailer_policy is reject: [0-9a-f]* carries \"$tr\"\$" <<<"$out"; } \
    && ok "trailer_policy reject fails a commit with the trailer '$tr'" || no "trailer '$tr': rc=$rc $out"
  [ "$(refs_all)" = "$r0" ] || no "left behind after a trailer: $(refs_all)"
  $DA local clean "$R39" --discard >/dev/null 2>&1 || rm -rf "$R39"
done
setans '.review.trailer_policy = "none"'; R40=$(newrun trailnone)
sed -i 's/^The manual and docs say what a name may hold\.$/&\n\nCo-Authored-By: Someone <someone@example.net>/' "$R40"/out/patches/0002-*.patch
out=$($DA review check "$R40/out" 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q '^scrub:' <<<"$out"; } && ok "trailer_policy none (the default) lets the trailer pass and prints nothing more" || no "trailer none: rc=$rc $out"
# a report-only run (no patches) is not scrubbed
setans '.review.scrub = "exit 1"'; mkdir -p "$T/rep2"; printf '# R\n\n## Findings\n\nnone\n' > "$T/rep2/report.md"
out=$($DA review check "$T/rep2" 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q '^scrub:' <<<"$out"; } && ok "a report-only run is not scrubbed" || no "report scrub: rc=$rc $out"
# a member's own check (the member mark in its environment) neither runs the command nor makes the checkout, and does not fail for it
MK=$T/scrub-ran; setans '.review.scrub = "touch '"$MK"'; exit 1"'
R41=$(newrun membercheck)
out=$(QARGI_MEMBER_RUN=$R41 $DA review check "$R41/out" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(scrubs "$out")" = 1 ] && grep -qx "scrub: not run (a member's check; the lead's check runs it)" <<<"$out" && [ ! -e "$MK" ]; } \
  && ok "a member's check does not run the scrub, says so and does not fail" || no "member check: rc=$rc $out"
setans '.review.scrub = "touch '"$MK"'; exit 1" | .review.trailer_policy = "reject"'
R42=$(newrun membertrail); r0=$(refs_all)
out=$(QARGI_MEMBER_RUN=$R42 $DA review check "$R42/out" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qx "scrub: not run (a member's check; the lead's check runs it)" <<<"$out" && [ ! -e "$MK" ] && [ "$(refs_all)" = "$r0" ]; } \
  && ok "and neither does a member's check make the checkout for a trailer policy" || no "member check, policy: rc=$rc $out"
out=$($DA review check "$R42/out" 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q '^scrub: FAIL' <<<"$out" && [ -e "$MK" ]; } && ok "the lead's check of the same run does run the scrub" || no "lead check: rc=$rc $out"
# --- review apply re-runs the declared scrub unless a passing `review check` recorded the same series; a failing scrub refuses before anything is made
CNT=$T/scrub-count; : > "$CNT"; runs() { wc -l < "$CNT" | tr -d ' '; }
setans '.review.scrub = "echo ran >> '"$CNT"'; echo stray debug line; exit 3"'
R50=$(newrun applyfail); h1=$(heads); w1=$(git -C "$A" worktree list)
out=$($DA review apply "$R50" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -qx 'scrub: FAIL stray debug line' <<<"$out" && grep -q 'nothing was applied' <<<"$out" && [ "$(runs)" = 1 ]; } \
  && ok "apply runs the declared scrub, and a failing scrub refuses it" || no "apply scrub fail: rc=$rc $out"
{ [ "$(heads)" = "$h1" ] && [ "$(git -C "$A" worktree list)" = "$w1" ] && [ ! -e "$R50/applied" ] && [ -z "$(find "$T/s" -maxdepth 1 \( -name 'apply-wt.*' -o -name 'scrub-wt.*' \))" ]; } \
  && ok "and nothing changed: no branch, worktree or record of an application" || no "apply scrub fail left: $(heads) | $(git -C "$A" worktree list)"
# a check that failed the scrub left no pass: the apply runs it again and refuses again
$DA review check "$R50/out" >/dev/null 2>&1; n=$(runs)
out=$($DA review apply "$R50" 2>&1); rc=$?
{ [ $rc != 0 ] && [ "$(runs)" = $((n + 1)) ] && ! grep -q 'scrub: skipped' <<<"$out"; } && ok "a scrub that failed at check is run again by apply, and refuses again" || no "failed check, apply: rc=$rc $out"
$DA local clean "$R50" --discard >/dev/null 2>&1 || rm -rf "$R50"
# a scrub that passes at apply with no check before it: it ran, and the branch is made
setans '.review.scrub = "echo ran >> '"$CNT"'; exit 0"'; : > "$CNT"
R51=$(newrun applypass)
out=$($DA review apply "$R51" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -qx 'scrub: ok' <<<"$out" && [ "$(runs)" = 1 ] && git -C "$A" rev-parse -q --verify agent/applypass >/dev/null; } \
  && ok "a scrub that passes at apply (no check before) runs once and the series is applied" || no "apply scrub pass: rc=$rc $out"
# a passing check for the same series: the apply does not run the scrub again, and says so on one line
: > "$CNT"; R52=$(newrun applyskip)
$DA review check "$R52/out" >/dev/null 2>&1; rc=$?
out=$($DA review apply "$R52" 2>&1); rc2=$?
{ [ $rc = 0 ] && [ $rc2 = 0 ] && [ "$(runs)" = 1 ] && [ "$(grep -c '^scrub:' <<<"$out")" = 1 ] && grep -qx 'scrub: skipped (review check passed it for this series)' <<<"$out" && git -C "$A" rev-parse -q --verify agent/applyskip >/dev/null; } \
  && ok "a passing check for the same series: apply does not run the scrub again and says so on one line" || no "apply skip: rc=$rc/$rc2 runs=$(runs) $out"
# the series changed after the check (a patch message edited): apply runs the scrub again
: > "$CNT"; R53=$(newrun applychanged)
$DA review check "$R53/out" >/dev/null 2>&1
sed -i 's/^The manual and docs say what a name may hold\.$/&\n\nAn added line./' "$R53"/out/patches/0002-*.patch
out=$($DA review apply "$R53" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(runs)" = 2 ] && grep -qx 'scrub: ok' <<<"$out" && ! grep -q 'scrub: skipped' <<<"$out"; } \
  && ok "a series changed after the check is scrubbed again by apply" || no "apply changed: rc=$rc runs=$(runs) $out"
# a series changed after a passing check into one the scrub refuses: apply refuses and changes nothing
setans '.review.scrub = "echo ran >> '"$CNT"'; ! grep -q poison internal/a.go docs/a.md"'; : > "$CNT"
R54=$(newrun applypoison); $DA review check "$R54/out" >/dev/null 2>&1; h1=$(heads)
sed -i 's/^+b$/+poison/' "$R54"/out/patches/0001-*.patch
out=$($DA review apply "$R54" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q '^scrub: FAIL' <<<"$out" && [ "$(runs)" = 2 ] && [ "$(heads)" = "$h1" ] && [ ! -e "$R54/applied" ]; } \
  && ok "a series changed after a passing check into one the scrub refuses: apply refuses, nothing changed" || no "apply poison: rc=$rc runs=$(runs) $out"
# a member's apply never runs the lead's scrub
: > "$CNT"; R55=$(newrun applymember)
out=$(QARGI_MEMBER_RUN=$R55 $DA review apply "$R55" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(runs)" = 0 ] && grep -qx "scrub: not run (a member's apply; the lead's apply runs it)" <<<"$out"; } \
  && ok "a member's apply does not run the scrub and says so" || no "member apply: rc=$rc runs=$(runs) $out"
# The patches are copied once: a member process that changes a patch while the scrub runs (here the scrub command does it, as it runs after the copy) changes what the
# run directory holds, not what was scrubbed and applied; no copy is left behind.
SWAP=$T/swap-target
printf '%s\n' 'echo ran >> "$1"' 'sed -i "s/^+b\$/+poison/" "$(cat "$2")"/out/patches/0001-*.patch' > "$T/swap.sh"
setans '.review.scrub = "sh '"$T"'/swap.sh '"$CNT"' '"$SWAP"'"'; : > "$CNT"
R58=$(newrun applyswap); printf '%s\n' "$R58" > "$SWAP"
out=$($DA review apply "$R58" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(runs)" = 1 ] && grep -q '^+poison$' "$R58"/out/patches/0001-*.patch \
  && [ "$(git -C "$A" show agent/applyswap~1:internal/a.go | wc -l)" = 2 ] && ! git -C "$A" show agent/applyswap~1:internal/a.go | grep -q poison \
  && [ -z "$(find "$T/s" -maxdepth 1 -name 'apply-in.*')" ]; } \
  && ok "apply scrubs and applies one copy of the patches: a patch changed in the run directory meanwhile is not what is applied, and no copy is left" \
  || no "apply copy: rc=$rc runs=$(runs) $out | $(git -C "$A" show agent/applyswap~1:internal/a.go 2>&1)"
setans '.review.scrub = "echo ran >> '"$CNT"'; exit 0"'
# --from-saved: the same rule, from the saved copy (the check's record is the lead's, not the run directory's)
: > "$CNT"; RS6=$(newrun savedskip); IS6=$(basename "$RS6")
$DA review check "$RS6/out" >/dev/null 2>&1; $DA local verify "$RS6" >/dev/null 2>&1; rm -rf "$RS6"
out=$($DA review apply --from-saved "$IS6" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(runs)" = 1 ] && grep -qx 'scrub: skipped (review check passed it for this series)' <<<"$out" && git -C "$A" rev-parse -q --verify agent/savedskip >/dev/null; } \
  && ok "--from-saved skips the scrub a passing check recorded for the saved series" || no "from-saved skip: rc=$rc runs=$(runs) $out"
RS7=$(newrun savedrun); IS7=$(basename "$RS7"); $DA local verify "$RS7" >/dev/null 2>&1; rm -rf "$RS7"; n=$(runs)
out=$($DA review apply --from-saved "$IS7" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(runs)" = $((n + 1)) ] && grep -qx 'scrub: ok' <<<"$out"; } && ok "--from-saved with no check before it runs the scrub from the saved copy" || no "from-saved run: rc=$rc $out"
# a trailer policy is part of the scrub: apply refuses a series with the trailer
setans '.review.trailer_policy = "reject"'; R56=$(newrun applytrailer); h1=$(heads)
sed -i 's/^The manual and docs say what a name may hold\.$/&\n\nCo-Authored-By: Someone <someone@example.net>/' "$R56"/out/patches/0002-*.patch
out=$($DA review apply "$R56" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q '^scrub: FAIL review.trailer_policy is reject' <<<"$out" && [ "$(heads)" = "$h1" ]; } && ok "apply refuses a series that the trailer policy rejects" || no "apply trailer: rc=$rc $out"
# no declared scrub: apply prints no scrub line
cp "$AF0" "$AF"; R57=$(newrun applynone)
out=$($DA review apply "$R57" 2>&1); rc=$?
{ [ $rc = 0 ] && ! grep -q '^scrub:' <<<"$out"; } && ok "with no declared scrub apply prints no scrub line" || no "apply none: rc=$rc $out"
cp "$AF0" "$AF"
exit $fail
