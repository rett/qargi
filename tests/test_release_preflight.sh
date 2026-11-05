#!/usr/bin/env bash
# The preflight of `qargi release start`: a man page's .TH line and an empty or missing changelog section refuse the start
# before anything changes; the first commit sets the .TH date and version. Run: tests/test_release_preflight.sh
set -u
cd "$(dirname "$0")/.." || exit 1
SRC=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"
mk() { # name: a repository with develop only (master too), man page and changelog set by the caller afterwards
  R=$T/$1; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
seal() { git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch -f develop && $REL verify 0.2.0 >/dev/null 2>&1; }
refuses() { # label expected-text-in-message
  local before out; before=$(git -C "$R" for-each-ref | md5sum)
  out=$($REL start 0.2.0 --date 2026-03-04 2>&1) && { no "$1: started"; return; }
  grep -q "$2" <<<"$out" && [ "$before" = "$(git -C "$R" for-each-ref | md5sum)" ] && ok "$1" || no "$1: $out"
}

mk good; mkdir "$R/man"; printf '.TH APP 1 "2026-01-01" "app 0.1.0"\n.SH NAME\napp\n' > "$R/man/app.1"
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && ok "a good project starts" || no "good start: $($REL start 0.2.0 2>&1)"
[ "$(git -C "$R" show release/0.2.0:man/app.1 | head -1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && [ "$(git -C "$R" rev-list --count develop..release/0.2.0)" = 1 ] && git -C "$R" show release/0.2.0:CHANGELOG.md | grep -q '^## \[0.2.0\] - 2026-03-04' && ok "the first commit sets the .TH date and version, with VERSION and the changelog" || no "th: $(git -C "$R" show release/0.2.0:man/app.1 | head -1)"

mk empthdr; mkdir "$R/man"; printf '.TH APP 1 "" "app 0.1.0"\n' > "$R/man/app.1"; printf '## [Unreleased]\n- x\n' > "$R/CHANGELOG.md"; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && [ "$(git -C "$R" show release/0.2.0:man/app.1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && ok "an empty date field is filled" || no "empty date"

mk noth; mkdir "$R/man"; printf '.SH NAME\napp\n' > "$R/man/app.1"; seal
refuses "a man page without a .TH line refuses" "man/app.1: it has no .TH line"
mk short; mkdir "$R/man"; printf '.TH APP 1\n' > "$R/man/app.1"; seal
refuses "a .TH line without date and version fields refuses" "man/app.1: its .TH line has no date and source"
mk nover; mkdir "$R/man"; printf '.TH APP 1 "2026-01-01" "app"\n' > "$R/man/app.1"; seal
refuses "a source field without a version refuses" "carries no version"

mk emptycl; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n\n## [0.1.0] - 2026-01-01\n- old\n' > "$R/CHANGELOG.md"; seal
refuses "an empty Unreleased refuses" "nothing under '## \[Unreleased\]'"
$REL start 0.2.0 --allow-empty-notes >/dev/null 2>&1 && ok "--allow-empty-notes waives it" || no "allow-empty"
mk nosect; printf '# Changelog\n\n## [0.1.0] - 2026-01-01\n- old\n' > "$R/CHANGELOG.md"; seal
refuses "a changelog without an Unreleased section refuses" "no '## \[Unreleased\]' section"

mk plain; seal
$REL start 0.2.0 >/dev/null 2>&1 && ok "a project with neither man page nor changelog is not checked" || no "plain: $($REL start 0.2.0 2>&1)"
# the generated manual page keeps the date `release start` set: regenerating it after the start must not empty the date again
mk regen; cp -r "$SRC/lib" "$SRC/skills" "$R/"; mkdir "$R/man"; printf '# Changelog\n\n## [Unreleased]\n- x\n' > "$R/CHANGELOG.md"
(cd "$R" && python3 lib/help.py man > man/qargi.1)
[ "$(head -1 "$R/man/qargi.1")" = '.TH QARGI 1 "" "qargi 0.1.0"' ] && ok "a first generation (no page yet) writes an empty date" || no "first generation: $(head -1 "$R/man/qargi.1")"
seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 || no "regen start: $($REL start 0.2.0 2>&1)"
git -C "$R" checkout -q release/0.2.0
(cd "$R" && python3 lib/help.py man > man/qargi.1)
[ "$(head -1 "$R/man/qargi.1")" = '.TH QARGI 1 "2026-03-04" "qargi 0.2.0"' ] && git -C "$R" diff --quiet && ok "regenerating the page after release start keeps its date (python3 lib/help.py man > man/qargi.1)" || no "regenerated: $(head -1 "$R/man/qargi.1")"
printf '.TH QARGI 1 "2031-05-06" "qargi 0.2.0"\n' > "$T/dated.1"
(cd "$R" && python3 lib/help.py man --keep-date "$T/dated.1" > "$T/kept.1")
[ "$(sed -n 1p "$T/kept.1")" = '.TH QARGI 1 "2031-05-06" "qargi 0.2.0"' ] && ok "--keep-date reads the date from the named file" || no "--keep-date: $(sed -n 1p "$T/kept.1")"

# --- the layout answers: release.version_file, release.changelog.*, release.man_pages, release.test_command, release.preflight
rel() { jq --argjson r "$1" '.release = $r' "$T/c/projects/$QARGI_PROJECT.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/$QARGI_PROJECT.json"; }
onbranch() { # BRANCH 'commands run in a checkout of it': one more commit there
  git -C "$R" worktree add -q "$T/wt" "$1" && (cd "$T/wt" && eval "$2" && git add -A && git commit -q -m edit); git -C "$R" worktree remove --force "$T/wt"
}
finish_plan() { $REL finish "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
CL='# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n'

# no version file: the version is the changelog heading and the tag
mk nofile; rm "$R/VERSION"; printf "$CL" > "$R/CHANGELOG.md"; rel '{"version_file":"none"}'; seal; git -C "$R" checkout -q -b parked
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && ! git -C "$R" cat-file -e release/0.2.0:VERSION 2>/dev/null && git -C "$R" show release/0.2.0:CHANGELOG.md | grep -q '^## \[0.2.0\] - 2026-03-04' && ok "version_file none: a project with no VERSION file starts, and the changelog carries the version" || no "version_file none: $($REL start 0.2.0 2>&1)"
$REL verify 0.2.0 >/dev/null 2>&1; t=$(finish_plan 0.2.0)
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "version_file none: finish tags the release from the changelog heading" || no "none finish: $($REL finish 0.2.0 --plan "$t" --approved go 2>&1)"
mk nofile2; rm "$R/VERSION"; printf "$CL" > "$R/CHANGELOG.md"; rel '{"version_file":"none"}'; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1; onbranch release/0.2.0 "sed -i 's/^## \[0.2.0\]/## [0.2.1]/' CHANGELOG.md"; $REL verify 0.2.0 >/dev/null 2>&1
out=$($REL finish 0.2.0 2>&1) && no "version_file none: finish without a heading for the version" || { grep -q "no released section for 0.2.0" <<<"$out" && ok "version_file none: finish refuses a changelog with no section for the version" || no "none finish heading: $out"; }
mk othfile; mkdir "$R/conf"; echo 0.1.0 > "$R/conf/version.txt"; printf "$CL" > "$R/CHANGELOG.md"; rel '{"version_file":"conf/version.txt"}'; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && [ "$(git -C "$R" show release/0.2.0:conf/version.txt)" = 0.2.0 ] && [ "$(git -C "$R" show release/0.2.0:VERSION)" = 0.1.0 ] && ok "version_file: a named file is bumped, VERSION is left alone" || no "named version file"
mk misfile; printf "$CL" > "$R/CHANGELOG.md"; rel '{"version_file":"conf/version.txt"}'; seal
refuses "a version_file that is not in the repository refuses" "release.version_file: conf/version.txt is not a file"

# changelog heading templates
mk tplver; printf '# Changelog\n\n## 0.2.0 (unreleased)\n\n- a thing\n\n## 0.1.0 (2026-01-01)\n- old\n' > "$R/CHANGELOG.md"; rel '{"changelog":{"unreleased":"## {version} (unreleased)","released":"## {version} ({date})"}}'; seal
$REL start 0.2.1 --date 2026-03-04 >/dev/null 2>&1; c=$(git -C "$R" show release/0.2.1:CHANGELOG.md)
grep -qx '## 0.2.1 (2026-03-04)' <<<"$c" && ! grep -q unreleased <<<"$c" && [ "$(grep -c '^## ' <<<"$c")" = 2 ] && ok "an unreleased heading that carries the version is renamed to the released heading" || no "template with version: $c"
mk tplplain; printf '# Changelog\n\n# Next\n\n- a thing\n\n# v0.1.0 on 2026-01-01\n- old\n' > "$R/CHANGELOG.md"; rel '{"changelog":{"unreleased":"# Next","released":"# v{version} on {date}"}}'; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1; c=$(git -C "$R" show release/0.2.0:CHANGELOG.md)
grep -qx '# Next' <<<"$c" && grep -qx '# v0.2.0 on 2026-03-04' <<<"$c" && ok "custom headings: the unreleased heading stays and the released one is written after it" || no "custom headings: $c"
mk tplmiss; printf '# Changelog\n\n## [Unreleased]\n- x\n' > "$R/CHANGELOG.md"; rel '{"changelog":{"unreleased":"# Next"}}'; seal
refuses "an unreleased template the changelog lacks refuses, naming it" "no '# Next' section"
mk tplbad; printf "$CL" > "$R/CHANGELOG.md"; rel '{"changelog":{"released":"## the release"}}'; seal
refuses "a released template without {version} refuses" "release.changelog.released: must contain {version}"
rel '{"changelog":{"released":"## {version} {when}"}}'; refuses "a template with another placeholder refuses" "the only placeholders are"

# manual pages: release.man_pages names them; the date and the version are always set, and finish refuses a page that lost them
mk manl; mkdir "$R/man" "$R/docs"; printf '.TH APP 1 "" "app 0.1.0"\n' > "$R/docs/app.1"; printf '.TH OTHER 1 "x" "other 0.1.0"\n' > "$R/man/other.1"; printf "$CL" > "$R/CHANGELOG.md"; rel '{"man_pages":["docs/app.1"]}'; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1; [ "$(git -C "$R" show release/0.2.0:docs/app.1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && [ "$(git -C "$R" show release/0.2.0:man/other.1)" = '.TH OTHER 1 "x" "other 0.1.0"' ] && ok "man_pages: only the listed pages are dated, with an empty date filled" || no "man_pages: $(git -C "$R" show release/0.2.0:docs/app.1)"
mk manmiss; printf "$CL" > "$R/CHANGELOG.md"; rel '{"man_pages":["docs/gone.1"]}'; seal
refuses "a listed man page that does not exist refuses" "release.man_pages: docs/gone.1 is not a file"
mk manempty; mkdir "$R/man"; printf '.TH APP 1 "2026-01-01" "app 0.1.0"\n' > "$R/man/app.1"; printf "$CL" > "$R/CHANGELOG.md"; seal; git -C "$R" checkout -q -b parked
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1; onbranch release/0.2.0 "printf '.TH APP 1 \"\" \"app 0.2.0\"\\n' > man/app.1"; $REL verify 0.2.0 >/dev/null 2>&1
out=$($REL finish 0.2.0 2>&1) && no "finish with an empty .TH date" || { grep -q "man/app.1 on release/0.2.0 has no date or no version" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "finish refuses a man page whose .TH date is empty (no release with an undated page)" || no "empty .TH finish: $out"; }
onbranch release/0.2.0 "printf '.TH APP 1 \"2026-03-04\" \"app 0.2.0\"\\n' > man/app.1"; $REL verify 0.2.0 >/dev/null 2>&1; t=$(finish_plan 0.2.0)
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && [ "$(git -C "$R" show 0.2.0:man/app.1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && ok "the tagged man page carries the date and the version" || no "tagged man page: $(git -C "$R" show 0.2.0:man/app.1 2>&1)"

# release.test_command: what verify runs (a line or a list of words), else test_command
mk vcmd; seal; jq '.test_command = "false"' "$T/c/projects/vcmd.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/vcmd.json"
$REL verify 0.2.0 >/dev/null 2>&1 && no "verify without release.test_command passed although test_command fails" || ok "verify runs test_command when release.test_command is not set"
rel '{"test_command":"echo release-check && true"}'; out=$($REL verify 0.2.0 2>&1) && grep -q "release-check" <<<"$out" && ok "verify runs release.test_command (a command line) instead of test_command" || no "release.test_command line: $out"
rel '{"test_command":["sh","-c","exit 0"]}'; $REL verify 0.2.0 >/dev/null 2>&1 && ok "release.test_command as a list of words" || no "release.test_command list"
rel '{"test_command":["sh","-c","exit 1"]}'; $REL verify 0.2.0 >/dev/null 2>&1 && no "a failing release.test_command passed" || ok "a failing release.test_command fails verify"

# release status says what the full-suite verdict is: the command that produced it and when it ran; a release.test_command that is not that
# command gets a line of its own, so the pass is not read as the release gate
mk stat; seal
out=$($REL status 0.2.0 2>&1)
grep -Eq '^no release/0.2.0 yet. develop is at [0-9a-f]+, full suite: pass at this head \(command: true; ran [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z; took [0-9]+s\)$' <<<"$out" && ! grep -q "note:" <<<"$out" && ok "status names the command, the time and the duration of the suite record, and says nothing more when release.test_command is not set" || no "status verdict: $out"
rel '{"test_command":"echo gate"}'; out=$($REL status 0.2.0 2>&1)
grep -q 'full suite: pass at this head (command: true; ran ' <<<"$out" && grep -qx '  note: release.test_command is "echo gate", not the command of that run: it is not the release gate (qargi release verify 0.2.0 runs it)' <<<"$out" && ok "a release.test_command that differs from the recorded command is named on its own line" || no "status note: $out"
$REL verify 0.2.0 >/dev/null 2>&1; $REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1; $REL verify 0.2.0 >/dev/null 2>&1; out=$($REL status 0.2.0 2>&1)
grep -q '^full suite: pass at this head (command: echo gate; ran ' <<<"$out" && ! grep -q "note:" <<<"$out" && ok "after the release's own verify the branch status shows that command and no note" || no "branch status: $out"
rel '{"test_command":"echo gate2"}'; out=$($REL status 0.2.0 2>&1)
grep -q '^full suite: pass at this head (command: echo gate; ran ' <<<"$out" && grep -qx '  note: release.test_command is "echo gate2", not the command of that run: it is not the release gate (qargi release verify 0.2.0 runs it)' <<<"$out" && ok "the note shows on the release branch status too" || no "branch note: $out"
# the record keeps how long the run took and the mode its command names (-j N, shard I/K); an older record without them still shows
rel '{"test_command":"echo gate -j 8 --shard 2/4"}'; $REL verify 0.2.0 >/dev/null 2>&1; out=$($REL status 0.2.0 2>&1)
grep -Eq '^full suite: pass at this head \(command: echo gate -j 8 --shard 2/4; ran [0-9T:Z-]+; took [0-9]+s; -j 8, shard 2/4\)$' <<<"$out" && ok "status shows the duration and the mode (-j N, shard I/K) of the suite record" || no "status mode: $out"
rel '{"test_command":"echo gate -j8"}'; $REL verify 0.2.0 >/dev/null 2>&1; out=$($REL status 0.2.0 2>&1)
grep -Eq '^full suite: pass at this head \(command: echo gate -j8; ran [0-9T:Z-]+; took [0-9]+s; -j 8\)$' <<<"$out" && ok "-jN is read as -j N" || no "status -jN: $out"
jq -c 'del(.seconds, .mode)' "$T/s/releases/stat-release_0.2.0.json" > "$T/rec.json" && cp "$T/rec.json" "$T/s/releases/stat-release_0.2.0.json"
out=$($REL status 0.2.0 2>&1)
grep -Eq '^full suite: pass at this head \(command: echo gate -j8; ran [0-9T:Z-]+\)$' <<<"$out" && ok "a record without a duration and a mode shows the command and the time only" || no "status old record: $out"

# release start lists the features merged into develop since the previous tag: the --no-ff merges "Merge branch 'feature/...'", one per line with the short sha
mergedev() { # BRANCH: a --no-ff merge of it into develop, with git's own message
  git -C "$R" worktree add -q --detach "$T/wt" develop && git -C "$T/wt" merge -q --no-ff "$1" -m "Merge branch '$1' into develop" && git -C "$R" update-ref refs/heads/develop "$(git -C "$T/wt" rev-parse HEAD)"
  git -C "$R" worktree remove --force "$T/wt"
}
mk feats; printf "$CL" > "$R/CHANGELOG.md"; git -C "$R" add -A; git -C "$R" commit -q -m one; git -C "$R" branch -f develop
git -C "$R" branch feature/old develop; onbranch feature/old "echo x > old.txt"; mergedev feature/old
git -C "$R" tag 0.1.0 develop
for n in feature/alpha feature/beta agent/task; do git -C "$R" branch "$n" develop; onbranch "$n" "echo x > $(basename "$n").txt"; mergedev "$n"; done
$REL verify 0.2.0 >/dev/null 2>&1; out=$($REL start 0.2.0 --date 2026-03-04 2>&1)
a=$(git -C "$R" log -1 --format=%h --grep "Merge branch 'feature/alpha'" develop); b=$(git -C "$R" log -1 --format=%h --grep "Merge branch 'feature/beta'" develop)
grep -qx 'features merged into develop since 0.1.0 (2):' <<<"$out" && grep -qx "  $a feature/alpha" <<<"$out" && grep -qx "  $b feature/beta" <<<"$out" && ! grep -q "feature/old\|agent/task" <<<"$out" && ok "release start lists the features merged since the previous tag, one per line with the short sha, and not older features or task merges" || no "feature list: $out"
mk nofeats; printf "$CL" > "$R/CHANGELOG.md"; git -C "$R" add -A; git -C "$R" commit -q -m one; git -C "$R" branch -f develop; git -C "$R" tag 0.1.0 develop
$REL verify 0.2.0 >/dev/null 2>&1; out=$($REL start 0.2.0 --date 2026-03-04 2>&1)
grep -qx 'no feature was merged into develop since 0.1.0' <<<"$out" && ok "and says so when there is none" || no "no features: $out"

# release.preflight: run by start and by push before anything changes; a non-zero exit refuses with the tail of its output
printf '#!/usr/bin/env bash\necho "$1" >> "%s/pre.log"\nif [ -f "%s/pre.fail" ]; then echo "preflight boom"; exit 3; fi\n' "$T" "$T" > "$T/pre.sh"
mk pre; printf "$CL" > "$R/CHANGELOG.md"; rel "$(jq -nc --arg s "$T/pre.sh" '{preflight:["bash",$s,"{version}"]}')"; seal
git init -q --bare "$T/pre-origin.git"; git -C "$R" remote add origin "$T/pre-origin.git"
touch "$T/pre.fail"; : > "$T/pre.log"
refuses "a failing preflight refuses the start, leaving no branch" "release.preflight failed (exit 3)"
out=$($REL start 0.2.0 2>&1); grep -q "preflight boom" <<<"$out" && grep -q "nothing was changed" <<<"$out" && ok "the refusal carries the tail of the preflight's output" || no "preflight tail: $out"
rm "$T/pre.fail"; : > "$T/pre.log"
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && [ "$(cat "$T/pre.log")" = 0.2.0 ] && ok "a passing preflight lets the start go on, and {version} is replaced in its arguments" || no "preflight start: $(cat "$T/pre.log")"
touch "$T/pre.fail"; t=$($REL push 0.2.0 | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
out=$(QARGI_GH=true $REL push 0.2.0 --plan "$t" --approved go 2>&1) && no "push with a failing preflight" || { grep -q "release.preflight failed (exit 3)" <<<"$out" && [ -z "$(git -C "$T/pre-origin.git" for-each-ref refs/heads/release)" ] && ok "a failing preflight refuses the push before anything is pushed" || no "push preflight: $out"; }
rm "$T/pre.fail"; QARGI_GH=true $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && [ -n "$(git -C "$T/pre-origin.git" for-each-ref refs/heads/release)" ] && ok "a passing preflight lets the push go on" || no "push passing preflight"
mk badpre; rel '{"preflight":"make check"}'; seal
refuses "a preflight that is text, not a list, refuses" "release.preflight: a command as a list of words"

rm -rf "$T"; exit $fail
