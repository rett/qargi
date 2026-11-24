#!/usr/bin/env bash
# The plain methodology (a project whose output is documents): methodology check accepts flow plain and names what breaks it, a new plain project
# end to end, the flow verbs refuse it (methodology-no-flow) and change nothing, a write run on a document through review check and apply, a run
# outside its SCOPE fails, and a gitflow project's scaffold, plan and template are what they were (tests/fixtures/gitflow-same).
# Run: tests/test_plain.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
# Lead-state fixtures use private modes and their own configured Git identities.
umask 077
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c" "$T/shm" "$T/scr"
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; }

# --- methodology check: flow plain
$DA methodology list | grep -q "^plain .*built-in" && $DA methodology check plain >/dev/null 2>&1 && ok "plain is a built-in methodology and passes methodology check" || no "plain: $($DA methodology check plain 2>&1)"
$DA methodology check >/dev/null 2>&1 && ok "every methodology checks out, the built-in ones together" || no "check: $($DA methodology check 2>&1)"
$DA methodology show plain | grep -q "^flow: plain" && $DA methodology show plain | grep -q "^branches: long-lived main; task agent/{slug}$" && ! $DA methodology show plain | grep -qE '^(release|ci):|None' \
  && ok "show prints the plain flow, its one branch and its task pattern, and no release or CI line" || no "show plain: $($DA methodology show plain)"
M=$T/c/methodologies/mine
variant() { # JQ-FILTER -> methodology "mine" as plain with the filter applied; the check's output
  rm -rf "$M"; mkdir -p "$M"; cp -r methodologies/plain/scaffold "$M/scaffold"
  jq ".name = \"mine\" | $1" methodologies/plain/methodology.json > "$M/methodology.json"
  $DA methodology check mine 2>&1
}
out=$(variant '.'); [ -z "$(grep -v '^methodologies: ok$' <<<"$out")" ] && ok "a copy of plain under another name passes" || no "copy of plain: $out"
for c in '.branches.release = "release/{version}"|a plain methodology has no branches.release' \
         '.branches.hotfix = "hotfix/{version}"|a plain methodology has no branches.hotfix' \
         '.branches.tag = "{version}"|a plain methodology has no branches.tag' \
         '.branches.feature = "feature/{name}"|a plain methodology has no branches.feature' \
         '.branches.long_lived = ["main", "develop"]|exactly one long-lived branch, not 2' \
         '.branches.long_lived = []|branches.long_lived is a list of branch names' \
         'del(.branches.task)|branches.task is a pattern containing {slug}' \
         '.branches.task = "agent/x"|branches.task is a pattern containing {slug}' \
         '.after_release = [{"id":"site","when":"site.enabled","next":"qargi release site {version}"}]|a plain methodology has no after_release' \
         '.versioning = {"file":"VERSION"}|a plain methodology has no versioning' \
         '.flow = "trunk"|flow is one of gitflow, plain' \
         '.work = "a line"|work is a list of steps, each a line of text' \
         '.work = ["a step", ""]|work is a list of steps, each a line of text' \
         '.work = ["a step", 3]|work is a list of steps, each a line of text' \
         '.work = ["two\nlines"]|work is a list of steps, each a line of text'; do
  f=${c%%|*}; want=${c#*|}
  out=$(variant "$f"); rc=0; $DA methodology check mine >/dev/null 2>&1 || rc=$?
  [ "$rc" = 1 ] && grep -qF -- "mine: " <<<"$out" && grep -qF -- "$want" <<<"$out" && ok "a plain methodology with ($f) fails the check, naming: $want" || no "variant $f: rc=$rc $out"
done
# a methodology without a flow is gitflow, which needs a release pattern: the plain shape is chosen, never guessed
out=$(variant 'del(.flow)'); grep -q "mine: branches.release is a pattern containing {version}" <<<"$out" && ok "without flow plain the one-branch methodology is still checked as gitflow and fails" || no "no flow: $out"
rm -rf "$M"

# --- a gitflow project is what it was: the scaffold, the show page, the check, the template and the plan of project new, byte for byte
G=tests/fixtures/gitflow-same
cmp -s <($DA methodology files gitflow --param project=acme --param year=2026) $G/files.json && ok "gitflow: the rendered scaffold is the recorded one, byte for byte" || no "gitflow files differ"
cmp -s <($DA methodology show gitflow | sed "s|^dir: .*|dir: DIR|") $G/show.txt && ok "gitflow: methodology show is the recorded text" || no "gitflow show differs"
cmp -s <($DA methodology check gitflow 2>&1) $G/check.txt && ok "gitflow: methodology check says what it said" || no "gitflow check differs"
cmp -s <($DA project template acme) $G/template.json && ok "gitflow: project template is the recorded answers, master and develop" || no "gitflow template differs: $($DA project template acme | diff - $G/template.json | head -5)"
cmp -s <($DA project template acme --methodology gitflow) $G/template.json && ok "gitflow: project template --methodology gitflow is the same" || no "template --methodology gitflow differs"
norm() { sed "s|$T|TMP|g; s/[0-9a-f]\{12\}/TOKEN/g"; }
cmp -s <($DA project new acme --dir "$T/acme" --param year=2026 2>&1 | norm) $G/new-plan.txt && ok "gitflow: the plan of project new is the recorded text (the token and the directory aside)" || no "gitflow plan differs: $($DA project new acme --dir "$T/acme" --param year=2026 2>&1 | norm | diff - $G/new-plan.txt | head -5)"
cmp -s <($DA project new acme --dir "$T/acme" --param year=2026 --json 2>&1 | norm) $G/new-plan.json && ok "gitflow: project new --json is the recorded object" || no "gitflow json differs"
[ ! -e "$T/acme" ] && ok "and showing those plans created nothing" || no "a plan created a directory"
$DA project template acme --methodology nosuch >/dev/null 2>&1 && no "template accepted an unknown methodology" || ok "project template refuses a methodology that does not exist"
variant '.branches.long_lived = ["main", "develop"]' >/dev/null
$DA project template acme --methodology mine >/dev/null 2>&1 && no "template accepted a methodology that fails the check" || ok "project template refuses a methodology that fails methodology check"
$DA project new acme --dir "$T/acme" --methodology mine >/dev/null 2>&1 && no "project new accepted a methodology that fails the check" || ok "project new refuses a methodology that fails methodology check, creating nothing"
[ ! -e "$T/acme" ] && ok "(nothing was created)" || no "created $T/acme"
rm -rf "$M"

# --- project template --methodology plain
tp=$($DA project template notes --methodology plain)
jq -e '.methodology == "plain" and .repo.long_lived == ["main"] and .roles.build.base == "@dispatcher" and .roles.write.base == "@dispatcher"' <<<"$tp" >/dev/null \
  && ok "project template --methodology plain: the long-lived branches come from the methodology (main only), not master and develop" || no "template plain: $tp"
jq '.repo.url = "https://github.com/acme/notes"' <<<"$tp" > "$T/tp.json"
$DA project validate "$T/tp.json" >/dev/null 2>&1 && ok "and the template validates once the url is filled in" || no "template validate: $($DA project validate "$T/tp.json" 2>&1)"

# --- project validate checks the methodology name
for bad in '"nosuch"' '"Bad Name"' '7' '""'; do
  jq --argjson m "$bad" '.methodology = $m' "$T/tp.json" > "$T/tpb.json"
  out=$($DA project validate "$T/tpb.json" 2>&1); rc=$?
  [ "$rc" = 1 ] && grep -q "^methodology: " <<<"$out" && ok "project validate refuses the methodology answer $bad" || no "validate methodology $bad: rc=$rc $out"
done
variant '.branches.release = "release/{version}"' >/dev/null
jq '.methodology = "mine"' "$T/tp.json" > "$T/tpb.json"
out=$($DA project validate "$T/tpb.json" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "^methodology: mine: a plain methodology has no branches.release" <<<"$out" && ok "project validate refuses a methodology that methodology check does not pass, with the reason" || no "validate failing methodology: rc=$rc $out"
rm -rf "$M"
jq '.repo.long_lived = ["master", "develop"]' "$T/tp.json" > "$T/tpb.json"
out=$($DA project validate "$T/tpb.json" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "^repo.long_lived: a project of the plain methodology plain has exactly one long-lived branch" <<<"$out" && ok "project validate refuses a plain project with two long-lived branches" || no "validate two long-lived: rc=$rc $out"
jq '.repo.long_lived = ["develop", "main"]' "$T/tp.json" > "$T/tpb.json"
$DA project validate "$T/tpb.json" >/dev/null 2>&1 && no "validate accepted two long-lived branches in the other order" || ok "(in either order of the answers)"
jq 'del(.methodology)' "$T/tp.json" > "$T/tpb.json";$DA project validate "$T/tpb.json" >/dev/null 2>&1 && ok "an answer with no methodology still validates (gitflow)" || no "no methodology answer"

# --- a new plain project, end to end
R=$T/notes
out=$($DA project new notes --methodology plain --dir "$R" --url https://github.com/acme/notes 2>&1); tok=$(tokof "$out")
[ -n "$tok" ] && [ ! -e "$R" ] && ok "the plan has a token and creates nothing" || no "plan: $out"
files=$(sed -n '/^  files:$/,/^  [a-z]/p' <<<"$out" | grep '^    ' | sed 's/^ *//' | tr '\n' ' ')
[ "$files" = "README.md CONTRIBUTING.md AGENTS.md artifacts/.gitkeep BACKLOG.md " ] && grep -q "^  git repository with the branches: main (the first is the initial one; work starts on the last)$" <<<"$out" \
  && ok "the plan lists main only and the five files" || no "plan files '$files': $out"
! grep -qE 'VERSION|CHANGELOG|\.github|Makefile|release start|develop|master' <<<"$out" && ok "the plan names no version, changelog, CI, release, develop or master" || no "plan words: $(grep -E 'VERSION|CHANGELOG|\.github|release start|develop|master' <<<"$out")"
jout=$($DA project new notes --methodology plain --dir "$R" --url https://github.com/acme/notes --json 2>&1)
jq -e --arg t "$tok" '.verb == "project new" and .token == $t and .exit == 0 and (.plan | contains("main (the first is the initial one"))' <<<"$jout" >/dev/null \
  && ok "project new --json carries the same token as the text plan, and the plan" || no "json: $jout"
jtok=$(jq -r .token <<<"$jout")
$DA project new notes --methodology plain --dir "$R" --url https://github.com/acme/notes --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong token is refused"
[ ! -e "$R" ] && ok "(and creates nothing)" || no "created on a wrong token"
out=$($DA project new notes --methodology plain --dir "$R" --url https://github.com/acme/notes --plan "$jtok" --approved "go ahead" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -d "$R/.git" ] && ok "the token from the json approves the same plan: the project is created" || no "create rc=$rc: $out"
! grep -q "release start" <<<"$out" && grep -q "git push -u origin main" <<<"$out" && ok "the next steps name main and no first release" || no "next steps: $out"
[ "$(git -C "$R" branch --show-current)" = main ] && [ "$(git -C "$R" branch --format='%(refname:short)')" = main ] && ok "the repository is on main and has no other branch (no develop, no master)" || no "branches: $(git -C "$R" branch -a)"
[ "$(git -C "$R" ls-files | tr '\n' ' ')" = "AGENTS.md BACKLOG.md CONTRIBUTING.md README.md artifacts/.gitkeep " ] && [ ! -e "$R/VERSION" ] && [ ! -e "$R/CHANGELOG.md" ] && [ ! -e "$R/.github" ] \
  && [ "$(git -C "$R" log --oneline | wc -l)" = 1 ] && [ -z "$(git -C "$R" status --porcelain)" ] && ok "one first commit holding the five files, no VERSION, no changelog, no CI, a clean tree" || no "files: $(git -C "$R" ls-files)"
grep -qx '## Development environment' "$R/AGENTS.md" && grep -q "^- \[some-id\]\|\`- \[some-id\]" "$R/BACKLOG.md" && ok "AGENTS.md has the Development environment section and the backlog file says how an item is written" || no "AGENTS.md or BACKLOG.md"
grep -rqiE '(^|[^[:alnum:]])qargi([^[:alnum:]]|$)' "$R" --exclude-dir=.git && no "the plain project mentions qargi" || ok "nothing in the plain project mentions qargi"
grep -rqE '\{\{[a-z_]+\}\}' "$R" --exclude-dir=.git && no "an unfilled placeholder remains" || ok "no placeholder is left"
grep -qiwE "states?|approved|publish" "$R/CONTRIBUTING.md" && no "CONTRIBUTING describes states that are not built" || ok "CONTRIBUTING describes nothing that is not there (no states, no publishing)"
jq -e '.methodology == "plain" and .repo.long_lived == ["main"] and .repo.path == "'"$R"'" and .backlog.file == "BACKLOG.md"' "$T/c/projects/notes.json" >/dev/null \
  && $DA project validate notes >/dev/null 2>&1 && ok "the stored answers name the plain methodology, main as the only long-lived branch and the backlog file, and validate" || no "answers: $(cat "$T/c/projects/notes.json")"
git -C "$R" config user.name lead; git -C "$R" config user.email lead@example.net
$DA project new gfp --dir "$T/gfp" --url https://github.com/acme/gfp --plan "$(tokof "$($DA project new gfp --dir "$T/gfp" --url https://github.com/acme/gfp)")" --approved go >/dev/null 2>&1
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
export QARGI_PROJECT=notes   # the project the verbs that take no --project act on

# --- the flow verbs refuse a plain project: exit 2, methodology-no-flow, nothing changed
snap() { { git -C "$R" for-each-ref --format='%(refname) %(objectname)'; git -C "$R" symbolic-ref HEAD; git -C "$R" status --porcelain; git -C "$R" worktree list
           find "$T/c" "$T/s" "$T/scr" -type f -exec sha256sum {} + | sed "s|$T|T|" | sort; } | sha256sum; }
before=$(snap)
refused() { # DESCRIPTION VERB-AS-SAID ARGS... -> the refusal of a flow verb
  local d=$1 v=$2; shift 2
  out=$($DA "$@" --project notes 2>&1); rc=$?
  [ "$rc" = 2 ] && head -n 1 <<<"$out" | grep -Eq "^qargi-refusal/1 \{\"code\":\"methodology-no-flow\",\"exit\":2,\"verb\":\"$v\",\"project\":\"notes\"" \
    && grep -q "^qargi: refused \[methodology-no-flow\] $v is refused: the project follows the plain methodology, which has no feature, release or hotfix flow (its flow is plain, or cannot be read: qargi methodology check)$" <<<"$out" \
    && grep -q "qargi local prepare, run and verify with --base BRANCH, qargi review check, save and apply, qargi local close and clean, and qargi backlog" <<<"$out" \
    && ok "$d: exit 2, methodology-no-flow, naming the methodology and the verbs that apply" || no "$d: rc=$rc $out"
}
refused "feature start" "feature start" feature start ideas
refused "feature list" "feature list" feature list
refused "feature merge" "feature merge" feature merge ideas agent/x
refused "feature finish" "feature finish" feature finish ideas
refused "release start" "release start" release start 1.0.0
refused "a hotfix (release start --hotfix)" "release start" release start 1.0.1 --hotfix
refused "release finish" "release finish" release finish 1.0.0
refused "branch prune" "branch prune" branch prune
refused "upstream status" "upstream status" upstream status
refused "changelog renumber" "changelog renumber" changelog renumber
[ "$(snap)" = "$before" ] && ok "none of them changed a ref, the checkout, a worktree, the answers or the state" || no "a refused flow verb changed something"
# a gitflow project is not refused: the same verb runs there
out=$($DA feature list --project gfp 2>&1); rc=$?
[ "$rc" = 0 ] && ! grep -q "methodology-no-flow" <<<"$out" && ok "the same verb on a gitflow project is not refused" || no "gitflow feature list: rc=$rc $out"

# a flow that is not a valid value is not run as gitflow: the flow verbs refuse it as they refuse plain (a methodology that is not found keeps the old behaviour)
jq '.methodology = "mine"' "$T/c/projects/notes.json" > "$T/c/projects/odd.json"
for v in '"Plain"' '["plain"]' 'null' '7' '""'; do
  variant ".flow = $v" >/dev/null
  out=$($DA feature list --project odd 2>&1); rc=$?
  [ "$rc" = 2 ] && grep -q "^qargi: refused \[methodology-no-flow\] feature list is refused: the project follows the mine methodology" <<<"$out" && ok "a methodology with flow $v is refused by the flow verbs (methodology-no-flow), never run as gitflow" || no "flow $v: rc=$rc $out"
done
variant '.' >/dev/null; printf '{"name": "mine", "flow": ' > "$M/methodology.json"
out=$($DA feature list --project odd 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "\[methodology-no-flow\] feature list is refused" <<<"$out" && ok "a methodology.json that cannot be read is refused by the flow verbs too" || no "unreadable: rc=$rc $out"
rm -rf "$M"; out=$($DA feature list --project odd 2>&1)
! grep -q "methodology-no-flow" <<<"$out" && ok "a methodology that is not found is not refused by its flow: the verb runs as it did" || no "absent methodology: $out"
rm -f "$T/c/projects/odd.json"
[ "$(snap)" = "$before" ] && ok "(and those refusals changed nothing)" || no "the odd-flow refusals changed something"

# --- the verbs that apply, with --base main: backlog, a write run on a document, review check and apply, a review run, a run outside its SCOPE
$DA backlog add first-note "write the first note" --project notes >/dev/null 2>&1 && grep -qx -- '- \[first-note\] write the first note' "$R/BACKLOG.md" && $DA backlog list --project notes 2>&1 | grep -q "first-note" \
  && ok "backlog add and list work on a plain project" || no "backlog: $($DA backlog list --project notes 2>&1)"
git -C "$R" checkout -q -- BACKLOG.md
prep() { # SLUG [prepare options...] -> RUN
  local s=$1; shift
  $DA local prepare --repo "$R" --base main --slug "$s" --scratch "$T/scr" "$@" 2>/dev/null | sed -n 's/^RUN=//p'
}
member() { # RUN FILE CONTENT SUBJECT -> the member's commit in the clone of RUN and its OUT: patches, series, manifest
  local r=$1 base
  base=$(git -C "$r/clone" rev-parse HEAD)
  ( cd "$r/clone" || exit 1
    mkdir -p "$(dirname "$2")"; printf '%s\n' "$3" > "$2"; git add -A
    GIT_AUTHOR_NAME=member GIT_AUTHOR_EMAIL=member@example.invalid GIT_COMMITTER_NAME=member GIT_COMMITTER_EMAIL=member@example.invalid git commit -q -m "$4" -m "The note says what the first reader needs to know."
    mkdir -p "$r/out/patches"; git format-patch -q -o "$r/out/patches" "$base..HEAD" )
  git -C "$r/clone" log --reverse --format='%H%x09%s' "$base..HEAD" | jq -R -s -c --arg donecmd "$(sed -n 's/^DONE: //p' "$r/task.md" | head -n 1)" --arg base "$base" '
    [split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", base:{branch:"main", sha:$base}, scope:["artifacts/"], done:{command:$donecmd, exit_code:0, output_tail:""}, commits:$c,
       commit_advice:($c|map(. + {why_separate:"one document", depends_on:[], builds_alone:true})), patch_groups:[{name:"first note", why:"one document", commits:($c|map(.sha))}]}' > "$r/out/manifest.json"
  echo "# series" > "$r/out/series.md"
}
printf 'Write the first note as artifacts/a.md.\n' > "$T/task.txt"
RUN=$(prep first --task-file "$T/task.txt" --done 'test -s artifacts/a.md' --scope artifacts/)
[ -n "$RUN" ] && grep -q '^BASE: main$' "$RUN/task.md" && grep -q '^SCOPE: artifacts/$' "$RUN/task.md" && grep -q '^DONE: test -s artifacts/a.md$' "$RUN/task.md" && ok "local prepare --base main cuts the run from main, with the DONE check and the SCOPE of the document" || no "prepare: $RUN"
member "$RUN" artifacts/a.md "# First note" "Notes: write the first note"
out=$($DA local verify "$RUN" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "local verify passes: the refs of the repository are as prepare saw them" || no "verify: rc=$rc $out"
out=$($DA review check "$RUN" 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "0 fail" <<<"$out" && ! grep -q "outside SCOPE" <<<"$out" && ok "review check passes a series that adds artifacts/a.md inside its SCOPE" || no "review check: rc=$rc $out"
main0=$(git -C "$R" rev-parse main)
out=$($DA review apply "$RUN" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$R" rev-list --count "main..agent/first")" = 1 ] && [ "$(git -C "$R" rev-parse agent/first~1)" = "$main0" ] && [ "$(git -C "$R" rev-parse main)" = "$main0" ] \
  && git -C "$R" cat-file -e agent/first:artifacts/a.md && ok "review apply makes agent/first at main with the commit; main did not move" || no "apply: rc=$rc $out"
git -C "$R" worktree add -q "$T/wt" agent/first && ( cd "$T/wt" && bash -c 'test -s artifacts/a.md' ) && ok "the DONE check, run by the lead on the applied branch, passes" || no "DONE on the applied branch"
git -C "$R" worktree remove --force "$T/wt"
# a review run on the applied version: a report with Findings and a verdict (a read-only run is looked up through the project's provider)
jq '.models = {provider: {local: "claude-code", cloud: "claude-platform"}}' "$T/c/projects/notes.json" > "$T/notes.tmp" && mv "$T/notes.tmp" "$T/c/projects/notes.json"
RV=$($DA local prepare --repo "$R" --base agent/first --slug review1 --scratch "$T/scr" --role review 2>/dev/null | sed -n 's/^RUN=//p')
if [ -n "$RV" ]; then
  printf '# Findings\n\nnone\n\n# Checked\n\nread artifacts/a.md on agent/first\n\nverdict: accept\n' > "$RV/out/report.md"
  printf '{"status":"DONE","commits":[],"artifacts":[{"path":"report.md","kind":"report"}]}\n' > "$RV/out/manifest.json"
  out=$($DA review check "$RV" 2>&1); rc=$?
  [ "$rc" = 0 ] && grep -q "OK report-only" <<<"$out" && ok "a review run on the applied document returns a report with a verdict, and review check passes it" || no "review run check: rc=$rc $out"
else
  no "a review run could not be prepared on the applied branch"
fi
# the reviewed branch is merged into main by the lead; the run is then cleaned
git -C "$R" merge -q --no-ff -m "Merge branch 'agent/first'" agent/first && out=$($DA local clean "$RUN" 2>&1); rc=$?
[ "$rc" = 0 ] && [ ! -d "$RUN" ] && ok "after the merge into main, local clean removes the run" || no "clean: rc=$rc $out"
[ -n "$RV" ] && $DA local clean "$RV" --discard >/dev/null 2>&1

# a run that writes outside its SCOPE fails review check, and review apply makes nothing of it
RUN2=$(prep wide --task-file "$T/task.txt" --done 'test -s artifacts/b.md' --scope artifacts/)
member "$RUN2" README.md "changed outside the scope" "Notes: rewrite the readme"
out=$($DA review check "$RUN2" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "FAIL .*outside SCOPE (artifacts/): README.md" <<<"$out" && ok "a run that changes README.md outside its SCOPE artifacts/ fails review check, naming the path" || no "scope check: rc=$rc $out"
out=$($DA review apply "$RUN2" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "outside SCOPE" <<<"$out" && ! git -C "$R" rev-parse -q --verify agent/wide >/dev/null && ok "and review apply refuses it and creates no branch" || no "scope apply: rc=$rc $out"
$DA local clean "$RUN2" --discard >/dev/null 2>&1

# after a passing verify the lead may fast-forward main (the one long-lived branch) and nothing else: a stray branch and a rewind of main are still refused
RUN3=$(prep guard --task-file "$T/task.txt" --done 'test -s artifacts/c.md' --scope artifacts/)
member "$RUN3" artifacts/c.md "# Third note" "Notes: write the third note"
$DA local verify "$RUN3" >/dev/null 2>&1 || no "(setup) the first verify of the guard run passes"
git -C "$R" branch stray
out=$($DA local verify "$RUN3" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "branch created, not an allowed branch: refs/heads/stray" <<<"$out" && ok "a branch the lead made by hand is not accepted after a passing verify, as in a git-flow project" || no "stray branch: rc=$rc $out"
git -C "$R" branch -q -D stray
tip=$(git -C "$R" rev-parse main); git -C "$R" update-ref refs/heads/main "$(git -C "$R" rev-parse main~1)"
out=$($DA local verify "$RUN3" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "branch rewritten (not a fast-forward): refs/heads/main" <<<"$out" && ok "a rewind of main is refused: only a fast-forward of the one long-lived branch is the lead's own move" || no "rewind: rc=$rc $out"
git -C "$R" update-ref refs/heads/main "$tip"
# the registry's snapshot of the answers holds the methodology of a plain project and nothing of the sort for a gitflow one
snapof() { jq -c --arg b "$(basename "$1")" 'select((.run | type) == "string" and (.run | endswith("/" + $b))) | .answers' "$T/s/local-runs.jsonl"; }
[ "$(snapof "$RUN3" | jq -r '.methodology')" = plain ] && ok "the registry's snapshot of a plain project's run has methodology plain" || no "plain snapshot: $(snapof "$RUN3")"
RUNG=$($DA local prepare --repo "$T/gfp" --base develop --slug gf --task-file "$T/task.txt" --done true --scratch "$T/scr" 2>/dev/null | sed -n 's/^RUN=//p')
[ -n "$RUNG" ] && [ -n "$(snapof "$RUNG")" ] && [ "$(snapof "$RUNG" | jq 'has("methodology")')" = false ] && [ "$(snapof "$RUNG" | jq -r '.repo.long_lived | join(",")')" = "master,develop" ] \
  && ok "the snapshot of a gitflow project's run has no methodology key (a gitflow run's record is what it was)" || no "gitflow snapshot: ${RUNG:-no run} $([ -z "$RUNG" ] || snapof "$RUNG")"
[ -z "$RUNG" ] || $DA local clean "$RUNG" --discard >/dev/null 2>&1
$DA local clean "$RUN3" --discard >/dev/null 2>&1

# the one long-lived branch is fast-forwarded, never created: with main gone when the run was prepared, a main made after the first passing verify is refused,
# as the creation of develop or master is in a git-flow project (the run is cut from another branch, agent/first)
tip=$(git -C "$R" rev-parse main)
git -C "$R" checkout -q --detach && git -C "$R" branch -q -D main
RUN4=$($DA local prepare --repo "$R" --base agent/first --slug nomain --task-file "$T/task.txt" --done 'test -s artifacts/d.md' --scope artifacts/ --scratch "$T/scr" 2>/dev/null | sed -n 's/^RUN=//p')
if [ -n "$RUN4" ]; then
  member "$RUN4" artifacts/d.md "# Fourth note" "Notes: write the fourth note"
  $DA local verify "$RUN4" >/dev/null 2>&1 && ok "(setup) a run prepared while main did not exist verifies" || no "(setup) verify of the run prepared without main"
  git -C "$R" branch main "$tip"
  out=$($DA local verify "$RUN4" 2>&1); rc=$?
  [ "$rc" = 2 ] && grep -q "branch created, not an allowed branch: refs/heads/main" <<<"$out" && ok "main created after a passing verify is refused: the one long-lived branch is fast-forwarded, never created" || no "created main: rc=$rc $out"
  $DA local clean "$RUN4" --discard >/dev/null 2>&1
else
  no "a run could not be prepared while main did not exist"
  git -C "$R" branch main "$tip"
fi
git -C "$R" checkout -q main

exit $fail
