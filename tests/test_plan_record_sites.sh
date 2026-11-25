#!/usr/bin/env bash
# The stored plan record (qargi.plan/0) of the plans that keep one since slice 2: every plan whose hashed input is plain lines or one printf of words. For each verb the
# plan is made for real on a scratch repository, home and state (no network: gh, ant, curl and systemd-run are stand-ins), and these are checked:
#   - the token the verb printed is the one the verb always made: the same sha256 of the hashed bytes, which the test writes out by hand (the printf the verb used before it
#     kept a record) from values it knows, so a record that changed a byte of the input would fail here;
#   - `qargi plan show TOKEN --json` gives the verb as lib/commands.py names it, the target PROJECT:OBJECT, the labels in order, one entry for each hashed line, and lines that
#     rebuild exactly those bytes;
#   - the verbs this test applies with the token it printed (a line "the token still applies": feature merge into a detached branch, upstream sync, release finish and the finish
#     cut off, release publish, release site, project new, project set, the waiver of feature verify, marshal key init, enable, signers add and forget, provider accept, skill
#     accept and unaccept) still apply. The other plans (release finish --keep, publish with assets, release verify's waiver, project unset, marshal resign and disable,
#     instances init, normalize and refresh-prompt, credential setup) are not applied here: their apply is covered by the tests of the verbs, which run beside this one;
#   - the record never decides a token (the last section): with a clock that is no time, or no temporary directory, or a target the record refuses, the plan still prints its
#     token and an apply that has no --plan is refused.
# A plan of one printf of words (marshal, the `|` plans of registry, credential and skills) is ONE line, because the record's lines are the hashed text split on a newline: it has
# one label. The units of the record are tests/test_plan_record.py; the first five verbs of slice 1 are tests/test_plan_record.sh.
# Run: tests/test_plan_record_sites.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; ROOT=$PWD; DA=$ROOT/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_LEAD=lead GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$T/fake"
unset QARGI_PROJECT
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, the verbs below would be refused as a member's
REL="$DA release"; F="$DA feature"
PLANS=$T/s/plans
plan_show() { "$DA" plan show "$@"; }
sha12() { sha256sum | cut -c1-12; }

# site TOKEN VERB TARGET LABELS WANTFILE [WHAT]: the plan the verb printed under TOKEN against the bytes the old code hashed (WANTFILE, written by the test). LABELS are `label:kind`
# in order, a label that took several lines once.
site() {
  local t=$1 verb=$2 target=$3 labels=$4 want=$5 what=${6:-$2} j got n
  [ -n "$t" ] || { no "$what: the verb printed no plan token"; return 1; }
  [ "$(sha12 < "$want")" = "$t" ] || { no "$what: the token $t is not the old one, $(sha12 < "$want"), of the same input"; return 1; }
  j=$(plan_show "$t" --json 2>&1) || { no "$what: plan show: $j"; return 1; }
  [ "$(jq -r '[.state, .schema, .verb, .context, (.target.project + ":" + .target.object), .token] | join("|")' <<<"$j")" = "valid|qargi.plan/0|$verb|lead|$target|$t" ] \
    || { no "$what: state, schema, verb, context, target or token: $(jq -c '[.state, .schema, .verb, .context, .target, .token]' <<<"$j")"; return 1; }
  got=$(jq -r '[.lines[] | .label + ":" + .kind] | reduce .[] as $l ([]; if .[-1] == $l then . else . + [$l] end) | join(" ")' <<<"$j")
  [ "$got" = "$labels" ] || { no "$what: labels and kinds: $got (expected $labels)"; return 1; }
  n=$(grep -c '' "$want"); [ "$(jq '.lines | length' <<<"$j")" = "$n" ] || { no "$what: $(jq '.lines | length' <<<"$j") lines, the input has $n"; return 1; }
  { jq -j '[.lines[].value] | join("\n")' <<<"$j"; [ "$(jq -r .input_newline <<<"$j")" != true ] || printf '\n'; } | cmp -s - "$want" || { no "$what: the lines do not rebuild the hashed bytes"; return 1; }
  [ "$(jq -r .input_sha256 <<<"$j")" = "$(sha256sum < "$want" | cut -d' ' -f1)" ] || { no "$what: input_sha256"; return 1; }
  [ "$(stat -c %a "$PLANS/$t.json")" = 600 ] || { no "$what: the record is not mode 600"; return 1; }
  ok "$what: the token is the old one, and the record has the verb, the target $target, $n line(s) with labels $labels, and lines that rebuild the hashed bytes"
}
# want FILE FORMAT ARGS...: the bytes the old code hashed, written by printf as the old code wrote them
want() { local f=$1; shift; printf "$@" > "$f"; }
# line TOKEN N: the value of line N (from 0) of the record
line() { plan_show "$1" --json | jq -r --argjson n "$2" '.lines[$n].value'; }

mkproj() { # NAME [EXTRA-JQ]: a repository with master, develop and a bare origin, the project's answers, the main checkout parked
  R=$T/$1; O=$T/$1-origin.git; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
  git init -q --bare "$O"; git -C "$R" remote add origin "$O"; git -C "$R" push -q origin master develop
  git -C "$R" checkout -q -b parked
  "$DA" project template "$1" | jq --arg p "$R" '.repo.url = "https://github.com/acme/x" | .repo.path = $p | .methodology = "gitflow" | .test_command = "true"' | jq "${2:-.}" > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
task() { # NAME [BASE]: a task branch with one commit, cut from BASE (develop)
  git -C "$R" branch "agent/$1" "${2:-develop}"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
rev() { git -C "$1" rev-parse -q --verify "$2" 2>/dev/null || echo none; }
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; *"release create"*) while [ $# -gt 0 ]; do [ "$1" = --notes-file ] && cp "$2" "%s/notes.copy"; shift; done; echo https://example.net/r;; esac\n' "$T" "$T" > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh

# ---------------------------------------------------------------------------------------------------------------------------- feature merge (a detached branch)
mkproj det '.repo.long_lived += ["docs-site"] | .repo.detached = ["docs-site"]'
git -C "$R" checkout -q --orphan docs-site && git -C "$R" rm -q -rf . && echo "docs home" > "$R/index.md" && git -C "$R" add -A && git -C "$R" commit -q -m docs && git -C "$R" checkout -q parked
task d1 docs-site
t=$($F merge docs-site agent/d1 | tok); want "$T/w" '%s\n%s\n%s\n%s\n%s\n' det docs-site "$(rev "$R" docs-site)" agent/d1 "$(rev "$R" agent/d1)"
site "$t" "feature merge" "det:docs-site" "project:name detached:ref head:sha task:ref task-head:sha" "$T/w" "feature merge into a detached branch"
$F merge docs-site agent/d1 --plan "$t" --approved go >/dev/null 2>&1 && [ "$(git -C "$R" rev-list --parents -n1 docs-site | wc -w)" = 3 ] && ok "feature merge into a detached branch: the token still applies" || no "detached merge apply"

# ---------------------------------------------------------------------------------------------------------------------------- upstream sync
U=$T/up; git init -q -b main "$U"; git init -q --bare "$T/up.git"; printf 'a\nb\n' > "$U/shared.txt"
git -C "$U" add -A; git -C "$U" commit -q -m base; git -C "$U" push -q "$T/up.git" main:main
mkproj ups '.repo.long_lived += ["upstream"] | .upstream = {remote:"upstream", branch:"main"}'
git -C "$R" remote add upstream "$T/up.git"; git -C "$R" fetch -q upstream; git -C "$R" branch -q upstream upstream/main >/dev/null 2>&1
echo more >> "$U/shared.txt"; git -C "$U" commit -q -am more; git -C "$U" push -q "$T/up.git" main:main
$DA upstream status >/dev/null 2>&1
t=$($DA upstream sync | tok); want "$T/w" '%s\n%s\n%s\n%s\n' ups upstream "$(rev "$R" upstream)" "$(git -C "$U" rev-parse main)"
site "$t" "upstream sync" "ups:upstream" "project:name into:ref head:sha upstream:sha" "$T/w" "upstream sync"
$DA upstream sync --plan "$t" --approved go >/dev/null 2>&1 && [ "$(rev "$R" upstream)" = "$(git -C "$U" rev-parse main)" ] && ok "upstream sync: the token still applies" || no "upstream sync apply"

# ---------------------------------------------------------------------------------------------------------------------------- release finish, and the finish that was cut off
mkproj rfn
$REL verify 0.2.0 >/dev/null 2>&1; $REL start 0.2.0 --date 2026-03-04 --plan "$($REL start 0.2.0 --date 2026-03-04 | tok)" --approved go >/dev/null 2>&1
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
h=$(rev "$R" release/0.2.0)
t=$($REL finish 0.2.0 | tok); want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' rfn release/0.2.0 "$h" develop "$(rev "$R" master)" "$(rev "$R" develop)" "" ""
site "$t" "release finish" "rfn:0.2.0" "project:name branch:ref head:sha second:ref master:sha second-head:sha keep:label ignore-checks:label" "$T/w" "release finish"
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && [ "$(rev "$R" refs/tags/0.2.0)" != none ] && ok "release finish: the token still applies" || no "release finish apply: $($REL finish 0.2.0 --plan "$t" --approved go 2>&1 | tail -3)"
# --keep and --ignore-checks are lines of the plan: the same plan with them is another token, the old one
$REL verify 0.3.0 >/dev/null 2>&1; $REL start 0.3.0 --date 2026-03-05 --allow-empty-notes --plan "$($REL start 0.3.0 --date 2026-03-05 --allow-empty-notes | tok)" --approved go >/dev/null 2>&1
t=$($REL push 0.3.0 | tok); $REL push 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
h=$(rev "$R" release/0.3.0)
t=$($REL finish 0.3.0 --keep | tok); want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' rfn release/0.3.0 "$h" develop "$(rev "$R" master)" "$(rev "$R" develop)" 1 ""
site "$t" "release finish" "rfn:0.3.0" "project:name branch:ref head:sha second:ref master:sha second-head:sha keep:label ignore-checks:label" "$T/w" "release finish --keep"

# a finish cut off after its push: the plan of the resume is the record of the run, one line
mkproj rres
REALGIT=$(command -v git); export REALGIT
cat > "$T/bin/git" <<'S'
#!/usr/bin/env bash
"$REALGIT" "$@"; rc=$?
if [ -n "${DIE_AFTER:-}" ] && [ ! -e "${DIE_FLAG:-/nonexistent}" ]; then
  case " $* " in *"$DIE_AFTER"*) : > "$DIE_FLAG"; kill -9 "$PPID";; esac
fi
exit $rc
S
chmod +x "$T/bin/git"; PATH=$T/bin:$PATH
$REL verify 0.2.0 >/dev/null 2>&1; $REL start 0.2.0 --date 2026-03-04 --plan "$($REL start 0.2.0 --date 2026-03-04 | tok)" --approved go >/dev/null 2>&1
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.2.0 | tok)
out=$(DIE_AFTER="push -q --atomic" DIE_FLAG=$T/die-a $REL finish 0.2.0 --plan "$t" --approved go 2>&1)   # the git stand-in kills the verb after its push
rec=$T/s/finish-intent/rres-release-0.2.0.json
[ -f "$rec" ] || no "(setup) no finish was cut off: $(ls "$T/s/finish-intent" 2>&1)"
t=$($REL finish 0.2.0 | tok); jq -S -c 'del(.done)' "$rec" > "$T/w"
site "$t" "release finish" "rres:0.2.0" "record:name" "$T/w" "release finish (cut off)"
[ "$(jq -r .verb "$rec")" = "release:finish" ] && ok "(and the record of the run is the one line that was hashed: its done list is not part of it)" || no "intent record: $(cat "$rec")"
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && [ ! -e "$rec" ] && ok "release finish (cut off): the token still applies" || no "resume apply: $($REL finish 0.2.0 --plan "$t" --approved go 2>&1 | tail -3)"
rm -f "$T/bin/git"

# ---------------------------------------------------------------------------------------------------------------------------- release publish: no assets, then assets and a signature-less record
R=$T/relas; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n### Added\n- first thing\n' > "$R/CHANGELOG.md"
cat > "$R/build.sh" <<'B'
#!/usr/bin/env bash
mkdir -p dist; echo "app $1" > "dist/app-$1.tar"; echo "docs" > dist/docs.zip
B
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.1.0 -m 0.1.0 && git -C "$R" branch develop && git -C "$R" checkout -q -b parked
git init -q --bare "$T/relas-origin.git"; git -C "$R" remote add origin "$T/relas-origin.git"
jq -n --arg p "$R" '{schema:1, project:"relas", methodology:"gitflow", repo:{url:"https://github.com/acme/relas", path:$p, long_lived:["master","develop"]}, test_command:"true", release:{assets_command:["bash","build.sh","{version}"]}}' > "$T/c/projects/relas.json"
export QARGI_PROJECT=relas
tc=$(rev "$R" "refs/tags/0.1.0^{commit}")
t=$($REL publish 0.1.0 | tok); : > "$T/gh.log"; $REL publish 0.1.0 --plan "$t" --approved go >/dev/null 2>&1; nh=$(sha256sum < "$T/notes.copy")
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' relas 0.1.0 "$tc" "$nh" "relas 0.1.0" "" ""
site "$t" "release publish" "relas:0.1.0" "project:name version:name tag:sha notes:sha title:name asset:label signature:sha" "$T/w" "release publish (no assets, not signed)"
grep -q "release create 0.1.0" "$T/gh.log" && ok "release publish: the token still applies" || no "publish apply: $(cat "$T/gh.log")"
$REL assets 0.1.0 >/dev/null 2>&1
out=$($REL publish 0.1.0 --asset-dir dist 2>&1); t=$(tok <<<"$out")
ahash=$(sed -n 's/^  | \([0-9a-f]\{64\}\)  \(.*\)$/\1 \2/p' <<<"$out"); ahash+=$'\n'   # as the verb builds it: a line for each file, each ended by a newline
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' relas 0.1.0 "$tc" "$nh" "relas 0.1.0" "$ahash" ""
site "$t" "release publish" "relas:0.1.0" "project:name version:name tag:sha notes:sha title:name asset:label signature:sha" "$T/w" "release publish (two assets: a line for each, one more for the end of the list)"
[ "$(plan_show "$t" --json | jq '[.lines[] | select(.label == "asset")] | length')" = 3 ] && ok "(three entries labelled asset: the two files and the empty line the list leaves; the basis groups them under one label)" || no "asset entries: $(plan_show "$t" --json | jq -c .lines)"
[ "$(jq -c '[.basis[].label]' "$PLANS/$t.json")" = '["project","version","tag","notes","title","asset","signature"]' ] && [ "$(jq '[.basis[] | select(.label == "asset") | .lines | length] | .[0]' "$PLANS/$t.json")" = 3 ] && ok "(and the basis key that plan-stale reads holds one entry for the assets)" || no "basis: $(jq -c .basis "$PLANS/$t.json")"

# ---------------------------------------------------------------------------------------------------------------------------- release site
R=$T/sitepub; git init -q -b master "$R"
cp -r "$ROOT/lib" "$R/lib"; cp "$ROOT/LICENSE" "$ROOT/README.md" "$R/"; echo 0.5.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.5.0] - 2026-03-01\n\n### Added\n- the first thing\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.5.0 -m 0.5.0 && git -C "$R" branch develop
git -C "$R" checkout -q --orphan gh-pages && git -C "$R" rm -rq --cached . && git -C "$R" clean -fdxq
mkdir -p "$R/site"; cp -r "$ROOT/tests/fixtures/site/pages" "$ROOT/tests/fixtures/site/static" "$ROOT/tests/fixtures/site/site.json" "$R/site/"
echo "hand pages and site configuration" > "$R/README.md"; git -C "$R" add -A && git -C "$R" commit -q -m "Site: the hand pages"
git -C "$R" checkout -q -f -b scratch develop
jq -n --arg p "$R" '{schema:1, project:"sitepub", methodology:"gitflow", test_command:"true", site:{enabled:true}, repo:{url:"https://github.com/acme/sitepub", path:$p, long_lived:["master","develop","gh-pages"], detached:["gh-pages"]}}' > "$T/c/projects/sitepub.json"
export QARGI_PROJECT=sitepub
tc=$(rev "$R" "refs/tags/0.5.0^{commit}"); s0=$(rev "$R" gh-pages)
t=$($REL site 0.5.0 | tok)
# the tree the plan hashes is the tree the apply commits, so the expected value is the tree of the commit the apply makes (read from git, not from the record) and the plan is checked after it
$REL site 0.5.0 --plan "$t" --approved go >/dev/null 2>&1 && [ "$(rev "$R" gh-pages)" != "$s0" ] && ok "release site: the token still applies" || no "site apply: $($REL site 0.5.0 --plan "$t" --approved go 2>&1 | tail -3)"
tree=$(git -C "$R" rev-parse "gh-pages^{tree}")
[ "$(line "$t" 5)" = "$tree" ] || no "release site: the tree in the plan, $(line "$t" 5), is not the tree of the commit the apply made, $tree"
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n' sitepub 0.5.0 "$tc" gh-pages "$s0" "$tree"
site "$t" "release site" "sitepub:0.5.0" "project:name version:name tag:sha site-branch:ref site-head:sha tree:sha" "$T/w" "release site (the tree is the one of the commit the apply made)"

# ---------------------------------------------------------------------------------------------------------------------------- project new
mkdir -p "$T/pn"
out=$($DA project new pnew --dir "$T/pn/pnew" 2>&1); t=$(tok <<<"$out")
files=$(python3 -I "$ROOT/lib/methodology.py" files gitflow --param project=pnew)
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$T/pn/pnew" gitflow "" "" "" "" "" "$(jq -S -c . <<<"$files")"
site "$t" "project new" "pnew:$T/pn/pnew" "directory:path methodology:name url:name deployment:name provider:name provider-local:name provider-cloud:name files:name" "$T/w" "project new"
$DA project new pnew --dir "$T/pn/pnew" --plan "$t" --approved go >/dev/null 2>&1 && [ -d "$T/pn/pnew/.git" ] && ok "project new: the token still applies" || no "project new apply: $($DA project new pnew --dir "$T/pn/pnew" --plan "$t" --approved go 2>&1 | tail -3)"

# ---------------------------------------------------------------------------------------------------------------------------- project set and unset of verify.environment
mkproj vdemo
$DA project set vdemo verify.environment '{"fds":"ci-like"}' >/dev/null 2>&1 || no "(setup) first declaration: $($DA project set vdemo verify.environment '{"fds":"ci-like"}' 2>&1)"
oid=$(python3 -I "$ROOT/lib/suite_env.py" id '{"fds":"ci-like"}'); nid=$(python3 -I "$ROOT/lib/suite_env.py" id '{"fds":"close"}')
out=$($DA project set vdemo verify.environment '{"fds":"close"}' 2>&1); t=$(tok <<<"$out")
want "$T/w" '%s\n%s\n%s\n' vdemo "$oid" "$nid"
site "$t" "project set" "vdemo:verify.environment" "project:name old-declaration:sha new-declaration:sha" "$T/w" "project set verify.environment (a loosening)"
$DA project set vdemo verify.environment '{"fds":"close"}' --plan "$t" --approved "the owner agreed" >/dev/null 2>&1 && [ "$(jq -c .verify.environment "$T/c/projects/vdemo.json")" = '{"fds":"close"}' ] && ok "project set: the token still applies" || no "project set apply"
out=$($DA project unset vdemo verify.environment 2>&1); t=$(tok <<<"$out")
want "$T/w" '%s\n%s\n%s\n' vdemo "$nid" ""
site "$t" "project unset" "vdemo:verify.environment" "project:name old-declaration:sha new-declaration:sha" "$T/w" "project unset verify.environment (the removal of a declaration)"

# ---------------------------------------------------------------------------------------------------------------------------- the waiver of a verify.environment part (feature verify and release verify)
mkproj swv
SE=$ROOT/lib/suite_env.py
mkdir -p "$T/fakebin"; cp "$ROOT/tests/fixtures/fake-systemd-run" "$T/fakebin/systemd-run"; chmod +x "$T/fakebin/systemd-run"
export FAKE_SYSTEMD_MODE_FILE=$T/mode FAKE_SYSTEMD_LOG=$T/fakelog; echo nouser > "$T/mode"
jq --arg c "touch $T/ran" '.verify = {environment: {cpu_quota: "max"}} | .test_command = $c' "$T/c/projects/swv.json" > "$T/swv.json" && mv "$T/swv.json" "$T/c/projects/swv.json"
python3 -I "$SE" approved set swv '{"cpu_quota":"max"}' --by test --state "$T/s" >/dev/null
sid=$(python3 -I "$SE" id '{"cpu_quota":"max"}')
$F start wf >/dev/null 2>&1
PATH_PLAIN=$PATH; PATH=$T/fakebin:$PATH
out=$($F verify wf 2>&1); t=$(tok <<<"$out")
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n' swv feature/wf "$(rev "$R" feature/wf)" "$sid" cpu "waiver 0"
site "$t" "feature verify" "swv:wf" "project:name branch:ref head:sha environment:sha part:label waiver:label" "$T/w" "feature verify (the waiver of cpu)"
$F verify wf --waive-environment cpu --plan "$t" --approved "the owner agrees" >/dev/null 2>&1; [ -e "$T/ran" ] && ok "feature verify: the waiver token still applies (the suite ran)" || no "waiver apply: $($F verify wf --waive-environment cpu --plan "$t" --approved ok 2>&1 | tail -3)"
# two parts: one entry for each, and the label is written once in the basis
jq '.verify = {environment: {cpu_quota: "max", fds: "ci-like"}}' "$T/c/projects/swv.json" > "$T/swv.json" && mv "$T/swv.json" "$T/c/projects/swv.json"
python3 -I "$SE" approved set swv '{"cpu_quota":"max","fds":"ci-like"}' --by test --state "$T/s" >/dev/null
sid2=$(python3 -I "$SE" id '{"cpu_quota":"max","fds":"ci-like"}')
out=$($REL verify 0.2.0 2>&1); t=$(tok <<<"$out")
[ -n "$t" ] && [ "$(plan_show "$t" --json | jq -r .verb)" = "release verify" ] && ok "release verify: the refusal's token is a plan with a record" || no "release verify waiver: $out"
br=develop   # release/0.2.0 is not started here, so the release verify runs on the base branch of the project: named here, not read from the record
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n' swv "$br" "$(rev "$R" "$br")" "$sid2" cpu "waiver 0"
site "$t" "release verify" "swv:0.2.0" "project:name branch:ref head:sha environment:sha part:label waiver:label" "$T/w" "release verify (the waiver of cpu; the branch is the base, develop)"
PATH=$PATH_PLAIN

# ---------------------------------------------------------------------------------------------------------------------------- marshal: one line of words each
mkproj mar
git -C "$R" branch feature/f3 develop; git -C "$R" branch feature/f4 develop
t=$($DA marshal key init --principal alice@ms | tok); want "$T/w" 'marshal key init %s' alice@ms
site "$t" "marshal key" "machine:alice@ms" "words:name" "$T/w" "marshal key init"
$DA marshal key init --principal alice@ms --plan "$t" --approved go >"$T/o" 2>&1; LA=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/o" | sed 's/^[[:space:]]*//')
[ -f "$T/c/credentials/marshal_ed25519" ] && [ -n "$LA" ] && ok "marshal key init: the token still applies, and prints the line to trust" || no "key init apply: $(cat "$T/o")"
t=$($DA marshal enable --project mar | tok); want "$T/w" 'marshal enable %s %s' mar origin
site "$t" "marshal enable" "mar:origin" "words:name" "$T/w" "marshal enable"
$DA marshal enable --project mar --plan "$t" --approved go >/dev/null 2>&1 && [ -f "$T/s/marshal/mar.enabled" ] && ok "marshal enable: the token still applies" || no "enable apply"
$DA marshal claim f3 --as alice --goal "the goal" --project mar >/dev/null 2>&1 || no "(setup) claim f3: $($DA marshal claim f3 --as alice --goal g --project mar 2>&1)"
t=$($DA marshal signers add --project mar --line "$LA" | tok); want "$T/w" 'marshal signers %s %s %s' add mar "$LA"
site "$t" "marshal signers" "mar:alice@ms" "words:name" "$T/w" "marshal signers add"
$DA marshal signers add --project mar --line "$LA" --plan "$t" --approved go >/dev/null 2>&1 && ok "marshal signers add: the token still applies" || no "signers add apply"
t=$($DA marshal enable --project mar --integrity advisory | tok); want "$T/w" 'marshal enable %s %s integrity=%s' mar origin advisory
site "$t" "marshal enable" "mar:origin" "words:name" "$T/w" "marshal enable --integrity advisory"
$DA marshal enable --project mar --integrity advisory --plan "$t" --approved go >/dev/null 2>&1
t=$($DA marshal resign f3 --project mar | tok); h3=$(git -C "$O" rev-parse refs/qargi/features/f3 2>/dev/null)
want "$T/w" 'marshal resign %s %s head=%s rev=%s lead=%s goal=%s' mar f3 "$h3" 1 alice "the goal"
site "$t" "marshal resign" "mar:f3" "words:name" "$T/w" "marshal resign"
$DA marshal claim f4 --as alice --goal four --project mar >/dev/null 2>&1
mk=$(jq -c '.f4' "$T/s/features/.accepted-mar.json" 2>/dev/null)
t=$($DA marshal forget f4 --project mar | tok); want "$T/w" 'marshal forget %s %s rev=%s oid=%s' mar f4 "$(jq -r '.[0]' <<<"$mk")" "$(jq -r '.[1]' <<<"$mk")"
site "$t" "marshal forget" "mar:f4" "words:name" "$T/w" "marshal forget"
$DA marshal forget f4 --project mar --plan "$t" --approved go >/dev/null 2>&1 && [ "$(jq -c '.f4' "$T/s/features/.accepted-mar.json")" = null ] && ok "marshal forget: the token still applies" || no "forget apply"
t=$($DA marshal disable --project mar | tok); want "$T/w" 'marshal disable %s integrity=%s' mar advisory
site "$t" "marshal disable" "mar:shared-refs" "words:name" "$T/w" "marshal disable (with integrity on)"

# the waiver of several parts: the function itself, with the values a refusal of cpu and fds would have: a line for each part, the label once in the basis
fn=$(sed -n '/^suite_env_token() {/,/^}/p' "$ROOT/lib/gitflow.sh")
t=$(PROJ=swv SE_BR=feature/x SE_HEAD=0123abc SUITE_ENV_ID=0123456789ab SE_GEN=2 SE_AGAIN="qargi feature verify x" DA_STATE=$T/s QARGI_TOOL=$ROOT bash -c '. "$1/lib/lib.sh"; '"$fn"'; suite_env_token cpu,fds "" record' _ "$ROOT")
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' swv feature/x 0123abc 0123456789ab cpu fds "waiver 2"
site "$t" "feature verify" "swv:x" "project:name branch:ref head:sha environment:sha part:label waiver:label" "$T/w" "the waiver of two parts"
[ "$(jq -c '[.basis[] | [.label, (.lines | length)]]' "$PLANS/$t.json")" = '[["project",1],["branch",1],["head",1],["environment",1],["part",2],["waiver",1]]' ] && ok "(the basis key has one entry, with two lines, for the label part)" || no "basis of the waiver: $(jq -c .basis "$PLANS/$t.json")"
t2=$(PROJ=swv SE_BR=feature/x SE_HEAD=0123abc SUITE_ENV_ID=0123456789ab SE_GEN=2 SE_AGAIN="qargi feature verify x" DA_STATE=$T/s QARGI_TOOL=$ROOT bash -c '. "$1/lib/lib.sh"; '"$fn"'; suite_env_token cpu,fds' _ "$ROOT")
[ "$t2" = "$t" ] && ok "(and the token without the record is the same)" || no "token without the record: $t2 $t"

# ---------------------------------------------------------------------------------------------------------------------------- provider accept
TOOL=$T/tool; copy_tool "$ROOT" "$TOOL"
# shellcheck source=fakeprov.sh
. "$ROOT/tests/fakeprov.sh"
NB='.capabilities.read_only_barrier |= (.value = "no" | .note = "nothing stops a write")'
fake_family "$ROOT" "$TOOL" nobarrier . "$NB" "$NB"
git init -q -b main "$T/repo-alpha"; git -C "$T/repo-alpha" commit -q --allow-empty -m one
"$DA" project template alpha | jq --arg r "$T/repo-alpha" '.repo.url = "https://github.com/example/alpha" | .repo.path = $r | .models.provider = {local: "nobarrier-local", cloud: "nobarrier-cloud"}' > "$T/alpha.json"
"$DA" project init alpha --answers "$T/alpha.json" --force >/dev/null 2>&1 || no "(setup) init alpha"
ACCEPT=("$TOOL/bin/qargi" provider accept nobarrier-cloud --surface cloud --no-barrier --project alpha --asked "review on cloud is fine here")
t=$("${ACCEPT[@]}" | tok); want "$T/w" '%s\n%s\n%s\n%s\n' nobarrier-cloud cloud alpha "review on cloud is fine here"
site "$t" "provider accept" "alpha:nobarrier-cloud cloud" "runtime:name surface:label project:name reason:name" "$T/w" "provider accept"
"${ACCEPT[@]}" --plan "$t" --approved go >/dev/null 2>&1 && jq -e '.models.accept_no_barrier.cloud' "$T/c/projects/alpha.json" >/dev/null && ok "provider accept: the token still applies" || no "provider accept apply"

# ---------------------------------------------------------------------------------------------------------------------------- instances: init (the agent's model), normalize and refresh-prompt, with a stand-in for ant
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
case $1 in
  auth) exit 0;;
  beta:agents) case $2 in retrieve) echo '{"id":"agent_B","version":1,"archived_at":null,"name":"old-agent","system":"an old prompt","model":{"id":"claude-sonnet-5-5","effort":{"type":"high"}}}';; *) echo '{}';; esac;;
  beta:deployments) echo '{"id":"depl_B","status":"active","archived_at":null,"name":"beta-build","budget":{"type":"limit"},"environment_id":"env_1","agent":{"id":"agent_B","version":1}}';;
  beta:environments) echo '{"name":"old-env"}';;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; PATH=$T/bin:$PATH
jq -n '{schema:1,project:"beta",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},
  models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/beta.json"
jq -n '{"beta-build":{location:"cloud",deployment_id:"depl_B",environment_id:"env_1",agent:{id:"agent_B",version_pinned:1,model:"claude-sonnet-5-5",effort:"high"}}}' > "$T/c/instances.json"
t=$($DA instances init --location cloud --deployment depl_B --model claude-opus-5-5 --asked "t" | tok); want "$T/w" '%s' "agent_B|1|claude-opus-5-5|high"
site "$t" "instances init" "beta:agent_B" "agent:name" "$T/w" "instances init (a change of the agent's model)"
out=$($DA instances normalize beta-build --asked "t" 2>&1); t=$(tok <<<"$out")
want "$T/w" '%s|%s' beta-build "$(sed -n 's/^  \([a-z]*\): \(.*\) -> \(.*\)$/\1:\2>\3;/p' <<<"$out" | tr -d '\n')"
[ -n "$(line "$t" 0 | sed -n 's/^beta-build|agent:old-agent>.*;$/x/p')" ] || no "(setup) the normalize plan text: $(line "$t" 0)"
site "$t" "instances normalize" "beta:beta-build" "renames:name" "$T/w" "instances normalize"
out=$($DA instances refresh-prompt beta-build --asked "t"); t=$(tok <<<"$out")
# the expected prompt is rendered here, by the function the verb calls (agent_prompt, for the role build of the project beta), not read from the record of the plan; the plan shows a
# line of it at most 150 characters wide, so the printed plan cannot stand for it
prompt=$(DA_STATE=$T/s QARGI_TOOL=$ROOT bash -c '. "$1/lib/lib.sh"; agent_prompt build beta' _ "$ROOT") || no "(setup) the prompt could not be rendered"
want "$T/w" '%s|%s|%s' 1 "$prompt" ""
site "$t" "instances refresh-prompt" "beta:beta-build" "prompt:name" "$T/w" "instances refresh-prompt (the rendered prompt, a line each, the version before and the pinned members after)"
[ "$(jq '.lines | length' "$PLANS/$t.json")" -gt 20 ] && ok "(the record holds the whole prompt: $(jq '.lines | length' "$PLANS/$t.json") lines)" || no "refresh-prompt lines"

# ---------------------------------------------------------------------------------------------------------------------------- credential setup
cat > "$T/bin/curl" <<'EOS'
#!/usr/bin/env bash
for a in "$@"; do url=$a; done
case $url in
  *"/branches/"*"/protection") printf '{"message":"Resource not accessible by personal access token"}\n403';;
  *"/repos/example/x") printf '{"full_name":"example/x","default_branch":"main","permissions":{"push":true,"admin":true}}\n200';;
  *"/user/repos"*) printf '[{"name":"r0"}]\n200';;
  *) printf '{"message":"Not Found"}\n404';;
esac
EOS
cat > "$T/bin/git" <<'EOS'
#!/usr/bin/env bash
if printf '%s\n' "$@" | grep -qx push; then case "$*" in *github.com/example/x.git*) exit 0;; *) exit 1;; esac; fi
exec /usr/bin/git "$@"
EOS
chmod 755 "$T/bin/curl" "$T/bin/git"
jq -n '{schema:1,project:"alpha2",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  lead:{model:"claude-opus-5-5",effort:"high"},teams:{t:{members:["build"]}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha2.json"
printf '%s' "github_pat_11AAAAAA0abcdefghijklmnopqrstuvwxyz0123456789SECRETVALUE" > "$T/tokfile"
CRED=("$DA" credential setup lead-push alpha2 --from-file "$T/tokfile")
t=$("${CRED[@]}" 2>&1 | tok); want "$T/w" '%s|%s|%s' alpha2 example/x "$T/c/credentials/alpha2-lead-push"
site "$t" "credential setup" "alpha2:example/x" "grant:name" "$T/w" "credential setup"
! grep -rq SECRETVALUE "$PLANS" && ok "(the token of the credential is no part of the plan: the record holds the name, the repository and the file)" || no "the secret is in a plan record"

# ---------------------------------------------------------------------------------------------------------------------------- skill accept and unaccept
R2=$T/skrepo; git init -q -b main "$R2"; echo x > "$R2/README"; git -C "$R2" add -A; git -C "$R2" commit -q -m one
jq -n --arg r "$R2" '{schema:1,project:"skp",repo:{url:"https://github.com/example/x",path:$r,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/skp.json"
mkdir -p "$R2/.claude/skills/risky"; printf -- '---\nname: risky\ndescription: Use for risky.\n---\n\nbody\n' > "$R2/.claude/skills/risky/SKILL.md"
sh=$(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1] + "/lib"); import packs_audit as A; print(A.strict_hash(sys.argv[2]))' "$ROOT" "$R2/.claude/skills/risky")
t=$($DA skill accept skp risky | tok); bind=$(line "$t" 0 | cut -d'|' -f7-)
want "$T/w" 'skill-accept|%s|%s|%s|%s|%s|%s' skp claude-code project:skp risky "$sh" "$bind"
site "$t" "skill accept" "skp:risky" "accept:name" "$T/w" "skill accept (the binding is read from the record: this checks the rebuild of the line, and the hash, runtime and project in front of it)"
[ -n "$bind" ] && [ "$bind" = "$(jq -cS . <<<"$bind")" ] && jq -e '(keys == ["composition","project","runtime","target"]) and .project == "skp" and .runtime == "claude-code" and (.composition | test("^[0-9a-f]{64}$"))' <<<"$bind" >/dev/null \
  && ok "(the last field of the line is the render binding, one canonical line of JSON for the project skp and the runtime claude-code, with a 64-digit composition: checked with jq, not against the record)" || no "binding: $bind"
$DA skill accept skp risky --plan "$t" --approved "read it" >/dev/null 2>&1 && jq -e '.projects.skp.risky' "$T/c/packs/accepted.json" >/dev/null && ok "skill accept: the token still applies" || no "skill accept apply"
t=$($DA skill unaccept skp risky | tok)
# the binding of an unaccept is the sha256 of the stored acceptance with its slot, project, scope, runtime and target: made here from the acceptance file, not from the plan's record
bind=$(python3 -I -c 'import hashlib, json, sys; r = json.load(open(sys.argv[1]))["projects"]["skp"]["risky"]; print(hashlib.sha256(json.dumps({"project": "skp", "scope": "project", "runtime": "claude-code", "target": None, "slot": "risky", "record": r}, sort_keys=True).encode()).hexdigest())' "$T/c/packs/accepted.json")
want "$T/w" 'skill-unaccept|%s|%s|%s|%s|%s|%s' skp claude-code project:skp risky "$sh" "$bind"
site "$t" "skill unaccept" "skp:risky" "unaccept:name" "$T/w" "skill unaccept (the binding made from the acceptance file)"
$DA skill unaccept skp risky --plan "$t" --approved "no longer" >/dev/null 2>&1 && jq -e '.projects.skp | has("risky") | not' "$T/c/packs/accepted.json" >/dev/null && ok "skill unaccept: the token still applies" || no "skill unaccept apply"

# ---------------------------------------------------------------------------------------------------------------------------- the token never depends on the record
# The record is a reading aid. When it cannot be kept (no temporary file: TMPDIR is gone; the store refuses: QARGI_PLAN_NOW is no time, or the target holds a control character)
# the plan still prints the one token it always printed, and an apply that was given no --plan is still refused: the empty token of a plan whose record failed must never equal
# the empty --plan of an apply.
nogo() { # WHAT: the output of the last command is a refusal for the plan, not an apply
  grep -q 'plan-missing\|plan-stale\|verify-env-change-unapproved' <<<"$out" || no "$1: the apply was not refused for its plan: $out"
}
# upstream sync: advance the upstream again; the plan is the plan of the upstream scenario above
UR=$T/ups; export QARGI_PROJECT=ups
rm -f "$T/bin/git"; hash -r   # the stand-in of the credential section refuses a push that is not to its repository
mkdir -p "$T/gone"; rmdir "$T/gone"
for cond in QARGI_PLAN_NOW=junk TMPDIR=$T/gone; do
  what="$cond"; [ "${cond%%=*}" != TMPDIR ] || what="TMPDIR gone"
  echo more2 >> "$U/shared.txt"; git -C "$U" commit -q -am "more $what"; git -C "$U" push -q "$T/up.git" main:main
  $DA upstream status >/dev/null 2>&1
  before=$(rev "$UR" upstream); h=$(git -C "$U" rev-parse main)
  want "$T/w" '%s\n%s\n%s\n%s\n' ups upstream "$before" "$h"
  out=$(env "$cond" "$DA" upstream sync 2>&1); t=$(tok <<<"$out")
  [ "$t" = "$(sha12 < "$T/w")" ] && ok "upstream sync ($what): the plan still prints the old token, $t, though its record could not be kept" || no "upstream sync ($what): the token is '$t', the input hashes to $(sha12 < "$T/w"): $out"
  [ ! -e "$PLANS/$t.json" ] && ok "(the record of that plan was not kept)" || no "($what) the record exists"
  out=$(env "$cond" "$DA" upstream sync --approved go 2>&1); rc=$?
  [ "$rc" != 0 ] && [ "$(rev "$UR" upstream)" = "$before" ] && ok "upstream sync --approved without --plan ($what): refused, upstream did not move" || no "upstream sync --approved ($what): rc=$rc, upstream moved to $(rev "$UR" upstream): $out"
  nogo "upstream sync ($what)"
  out=$(env "$cond" "$DA" upstream sync --plan 000000000000 --approved go 2>&1); rc=$?
  [ "$rc" != 0 ] && [ "$(rev "$UR" upstream)" = "$before" ] && ok "upstream sync with a token that is not the plan's ($what): refused, upstream did not move" || no "upstream sync wrong token ($what): $out"
  $DA upstream sync --plan "$t" --approved go >/dev/null 2>&1 && [ "$(rev "$UR" upstream)" = "$h" ] && ok "(and the token of the plan applies: the record is not what is checked)" || no "($what) apply with the token"
done
# project set of a loosening
mkproj vloose
$DA project set vloose verify.environment '{"fds":"ci-like"}' >/dev/null 2>&1 || no "(setup) first declaration"
oid=$(python3 -I "$ROOT/lib/suite_env.py" id '{"fds":"ci-like"}'); nid=$(python3 -I "$ROOT/lib/suite_env.py" id '{"fds":"close"}')
for cond in QARGI_PLAN_NOW=junk TMPDIR=$T/gone; do
  what="$cond"; [ "${cond%%=*}" != TMPDIR ] || what="TMPDIR gone"
  want "$T/w" '%s\n%s\n%s\n' vloose "$oid" "$nid"
  out=$(env "$cond" "$DA" project set vloose verify.environment '{"fds":"close"}' 2>&1); t=$(tok <<<"$out")
  [ "$t" = "$(sha12 < "$T/w")" ] && ok "project set verify.environment ($what): the plan of the loosening still prints the old token, $t" || no "project set ($what): the token is '$t', not $(sha12 < "$T/w"): $out"
  out=$(env "$cond" "$DA" project set vloose verify.environment '{"fds":"close"}' --approved w 2>&1); rc=$?
  [ "$rc" != 0 ] && [ "$(jq -c .verify.environment "$T/c/projects/vloose.json")" = '{"fds":"ci-like"}' ] && ok "project set (a loosening) --approved without --plan ($what): refused, the declaration is as it was" || no "project set --approved ($what): rc=$rc, now $(jq -c .verify.environment "$T/c/projects/vloose.json"): $out"
  nogo "project set ($what)"
done
# project new with a directory whose name holds a tab (the record refuses the target of such a plan; the plan still has its token)
TABDIR=$T/pn/x$'\t'y
want "$T/w" '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$TABDIR" gitflow "" "" "" "" "" "$(jq -S -c . <<<"$(python3 -I "$ROOT/lib/methodology.py" files gitflow --param project=ptab)")"
for cond in QARGI_PLAN_NOW=junk TMPDIR=$T/gone; do
  what="$cond"; [ "${cond%%=*}" != TMPDIR ] || what="TMPDIR gone"
  out=$(env "$cond" "$DA" project new ptab --dir "$TABDIR" 2>&1); t=$(tok <<<"$out")
  [ "$t" = "$(sha12 < "$T/w")" ] && ok "project new ($what, a directory with a tab): the plan prints the old token, $t" || no "project new ($what): the token is '$t', not $(sha12 < "$T/w"): $out"
  out=$(env "$cond" "$DA" project new ptab --dir "$TABDIR" --approved go 2>&1); rc=$?
  [ "$rc" != 0 ] && [ ! -e "$TABDIR" ] && [ ! -e "$T/c/projects/ptab.json" ] && ok "project new --approved without --plan ($what, a directory with a tab): refused, nothing was created" || no "project new --approved ($what): rc=$rc: $out"
  nogo "project new ($what)"
done
# the directory with a tab, with nothing wrong with the environment: the plan prints a token and its record, with the tab shown as ? in the target
out=$($DA project new ptab --dir "$TABDIR" 2>&1); rc=$?; t=$(tok <<<"$out")
[ "$rc" = 0 ] && [ "$t" = "$(sha12 < "$T/w")" ] && [ "$(jq -r '.target.object' "$PLANS/$t.json")" = "$T/pn/x?y" ] && ok "project new with a tab in the directory: rc 0, the old token, and the target of the record has the tab as ?" || no "project new with a tab: rc=$rc $out"
# a principal of marshal key init that holds a tab, or is over 200 characters: the plan prints its token as before the record (rc 0), and the apply refuses it as before
LONGP=$(printf 'p%.0s' $(seq 201)); TABP=$'al\tice@ms'
for pr in "$TABP" "$LONGP"; do
  what="a principal with a tab"; [ "$pr" != "$LONGP" ] || what="a principal of 201 characters"
  rm -f "$T/c/credentials/marshal_ed25519" "$T/c/credentials/marshal_ed25519.pub"   # the key the section above made
  out=$($DA marshal key init --principal "$pr" 2>&1); rc=$?; t=$(tok <<<"$out")
  want "$T/w" 'marshal key init %s' "$pr"
  [ "$rc" = 0 ] && [ "$t" = "$(sha12 < "$T/w")" ] && ok "marshal key init, $what: the plan prints its token (rc 0), the old one" || no "marshal key init, $what: rc=$rc token '$t': $out"
  if [ "$pr" = "$TABP" ]; then [ "$(jq -r '.target.object' "$PLANS/$t.json")" = "alice@ms" ] && ok "(the target of the record is the principal without the tab)" || no "target: $(jq -c .target "$PLANS/$t.json")"
  else [ "$(jq -r '.target.object | length' "$PLANS/$t.json")" = 200 ] && ok "(the target of the record is cut to 200 characters)" || no "target: $(jq -c .target "$PLANS/$t.json" | cut -c1-80)"; fi
  out=$($DA marshal key init --principal "$pr" --plan "$t" --approved go 2>&1); rc=$?
  [ "$rc" != 0 ] && [ ! -e "$T/c/credentials/marshal_ed25519" ] && ok "(and the apply refuses it, as before: no key was made)" || no "marshal key init apply, $what: rc=$rc: $out"
done
# need_plan itself: no gate accepts an empty expected token, whatever --plan holds
for pa in "" x; do
  out=$(PLAN_ARG=$pa DA_STATE=$T/s QARGI_TOOL=$ROOT bash -c '. "$1/lib/lib.sh"; need_plan ""; echo APPLIED' _ "$ROOT" 2>&1); rc=$?
  [ "$rc" != 0 ] && ! grep -q APPLIED <<<"$out" && grep -q 'internal error: no plan token to check; nothing was changed' <<<"$out" && ok "need_plan with an empty expected token and --plan '$pa': an internal error, nothing applied" || no "need_plan empty ($pa): rc=$rc $out"
done

exit $fail
