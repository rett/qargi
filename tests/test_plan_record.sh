#!/usr/bin/env bash
# The stored plan record (qargi.plan/0) of the verbs that keep one: branch prune, feature finish (its plan and the plan of a finish that was cut off), release plan,
# release start and release push. Each plan is made for real, on a scratch repository with a bare origin, and its record in STATE/plans/TOKEN.json is read back: the verb,
# the target, the labels and kinds of the lines, the lines that rebuild the exact bytes that were hashed (input_sha256, the first 12 digits of which are the token the verb
# printed), the old `basis` key, mode 600, and what `qargi plan show TOKEN` prints. A dry run keeps nothing. The units of the record (a label list shorter or longer than
# the input, a final newline or none, each refusal of plan show) are tests/test_plan_record.py.
# Run: tests/test_plan_record.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_LEAD=lead GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin"
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, the verbs below would be refused as a member's
REL="$DA release"; F="$DA feature"; B="$DA branch"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; esac\n' "$T" > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh
PLANS=$T/s/plans
# plan_show ARGS: qargi plan show through bin/qargi once it routes the command (`plan) exec`), until then lib/plan.py itself: the same program
if grep -q 'plan) exec' "$DA"; then plan_show() { "$DA" plan show "$@"; }; else plan_show() { python3 -I "$(dirname "$DA")/../lib/plan.py" show "$@"; }; fi

mkproj() { # NAME: a repository with master, develop and a bare origin, the project's answers, the main checkout parked
  R=$T/$1; O=$T/$1-origin.git; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
  git init -q --bare "$O"; git -C "$R" remote add origin "$O"; git -C "$R" push -q origin master develop
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
task() { # NAME [BASE]: a task branch with one commit, cut from BASE (develop)
  git -C "$R" branch "agent/$1" "${2:-develop}"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
# chk TOKEN VERB TARGET LABELS [WHAT]: the record of the plan the verb printed under TOKEN. LABELS are the labels with their kinds in order, `label:kind`, a label that takes several lines once.
chk() {
  local f=$PLANS/$1.json what=${5:-$2} got
  [ -f "$f" ] && [ "$(stat -c %a "$f")" = 600 ] && [ "$(stat -c %a "$PLANS")" = 700 ] || { no "$what: no record of mode 600 at $f"; return; }
  [ "$(jq -r '[.schema, .verb, .context, (.target.project + ":" + .target.object), .token] | join("|")' "$f")" = "qargi.plan/0|$2|lead|$3|$1" ] || { no "$what: schema, verb, context, target or token: $(jq -c '[.schema, .verb, .context, .target, .token]' "$f")"; return; }
  got=$(jq -r '[.lines[] | .label + ":" + .kind] | reduce .[] as $l ([]; if .[-1] == $l then . else . + [$l] end) | join(" ")' "$f")
  [ "$got" = "$4" ] || { no "$what: labels and kinds: $got (expected $4)"; return; }
  # the lines rebuild the bytes that were hashed: their hash is input_sha256, the start of which is the token the verb printed
  got=$({ jq -j '[.lines[].value] | join("\n")' "$f"; [ "$(jq -r .input_newline "$f")" != true ] || printf '\n'; } | sha256sum | cut -d' ' -f1)
  [ "$got" = "$(jq -r .input_sha256 "$f")" ] && [ "${got:0:12}" = "$1" ] || { no "$what: the lines do not hash to input_sha256 and the token: $got"; return; }
  jq -e '(.created | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$")) and (.basis | length > 0)' "$f" >/dev/null || { no "$what: created or basis"; return; }
  jq -e '([.lines[].label] | reduce .[] as $l ([]; if .[-1] == $l then . else . + [$l] end)) as $l | (.basis | map(.label))[0:($l | length)] == $l' "$f" >/dev/null || { no "$what: the basis key does not hold the labels of the lines"; return; }
  out=$(plan_show "$1" 2>&1) && grep -q "^plan $1: $2 (lead)$" <<<"$out" && grep -q "^target: ${3%%:*} ${3#*:}$" <<<"$out" || { no "$what: plan show: $out"; return; }
  ok "$what: the record of $1 has the verb, the target, the labels and kinds, lines that rebuild the hashed bytes, and plan show prints it"
}

# ---------------------------------------------------------------------------------------------------------------------------- branch prune
mkproj prn
$F start pa >/dev/null 2>&1; task t1 feature/pa; task t2 feature/pa; $F merge pa agent/t1 >/dev/null 2>&1; $F merge pa agent/t2 >/dev/null 2>&1
$B prune --dry-run >"$T/do" 2>&1; dt=$(tok < "$T/do")
[ -n "$dt" ] && [ ! -e "$PLANS/$dt.json" ] && ok "branch prune --dry-run keeps no record" || no "prune dry run: $dt $(ls -A "$PLANS" 2>&1)"
plan_show "$dt" >/dev/null 2>"$T/de"; [ "$?" = 1 ] && grep -q '"code":"plan-unknown"' "$T/de" && ok "plan show of the token of a dry run: plan-unknown" || no "plan show of a dry run: $(cat "$T/de")"
pp=$($B prune | tok)
[ "$pp" = "$dt" ] && ok "the token of the dry run is the plain plan's" || no "prune tokens: $pp $dt"
chk "$pp" "branch prune" "prn:merged-branches" "project:name remote:count branches:ref"
[ "$(jq -r '[.lines[] | select(.label == "branches") | .value] | length' "$PLANS/$pp.json")" = 3 ] && jq -e '[.lines[] | select(.label == "branches") | .value] | map(startswith("local agent/t")) == [true, true, false]' "$PLANS/$pp.json" >/dev/null \
  && ok "a label that took several lines is written out for each: one entry for each branch (and the line 'remote ' that the plan hashes with none)" || no "prune lines: $(jq -c .lines "$PLANS/$pp.json")"
git -C "$R" push -q origin agent/t1
rp=$($B prune --remote | tok)
chk "$rp" "branch prune" "prn:merged-branches+origin" "project:name remote:count branches:ref" "branch prune --remote"
[ "$(jq -r '.lines[1].value' "$PLANS/$rp.json")" = 1 ] && ok "--remote is the count 1 in the second line" || no "prune --remote line: $(jq -c .lines "$PLANS/$rp.json")"

# ---------------------------------------------------------------------------------------------------------------------------- feature finish
mkproj fin
$F start fa >/dev/null 2>&1; task t1 feature/fa; $F merge fa agent/t1 >/dev/null 2>&1; $F verify fa >/dev/null 2>&1
before=$(find "$PLANS" -type f 2>/dev/null | sort | md5sum)
$F finish fa --dry-run >"$T/do" 2>&1; dt=$(tok < "$T/do")
[ -n "$dt" ] && [ ! -e "$PLANS/$dt.json" ] && [ "$before" = "$(find "$PLANS" -type f 2>/dev/null | sort | md5sum)" ] && ok "feature finish --dry-run keeps no record" || no "finish dry run: $dt"
ft=$($F finish fa | tok)
chk "$ft" "feature finish" "fin:fa" "project:name branch:ref head:sha develop:sha keep:label delete-merged:label origin-branch:sha push:label"
[ "$ft" = "$dt" ] && [ "$(jq -r '.lines | map(.value) | .[1]' "$PLANS/$ft.json")" = feature/fa ] && ok "the dry run's token is the plain plan's, and the branch line holds the branch" || no "finish: $ft $dt"
# a finish that was cut off: its plan is the record, one line
fh=$(git -C "$R" rev-parse feature/fa); dv=$(git -C "$R" rev-parse develop)
mkdir -p "$T/s/finish-intent"
jq -nc --arg d0 "$dv" --arg m "$fh" --arg h "$fh" '{schema:1, verb:"feature:finish", project:"fin", name:"fa", pushed:false, refs:[{ref:"refs/heads/develop", local_old:$d0, origin_old:"", new:$m}], ctx:{head:$h, keep:"1", pushd:"", pushwhy:"the repository has no origin", rdel:"", k:"k"}, done:[]}' > "$T/s/finish-intent/fin-feature-fa.json"
rt=$($F finish fa | tok)
chk "$rt" "feature finish" "fin:fa" "record:name" "feature finish (cut off)"
[ "$(jq -r '.lines | length' "$PLANS/$rt.json")" = 1 ] && jq -e '.lines[0].value | fromjson | .name == "fa"' "$PLANS/$rt.json" >/dev/null && ok "the record of a cut-off finish is one line: the intent record as the plan hashed it" || no "finish record line: $(jq -c .lines "$PLANS/$rt.json")"
rm -f "$T/s/finish-intent/fin-feature-fa.json"

# ---------------------------------------------------------------------------------------------------------------------------- release plan, start and push
mkproj rel
$REL verify 0.2.0 >/dev/null 2>&1
$REL plan 0.2.0 --date 2026-03-04 --dry-run >"$T/do" 2>&1; dt=$(tok < "$T/do")
[ ! -e "$PLANS/$dt.json" ] && ok "release plan --dry-run keeps no record of its own" || no "release plan dry run: $dt"
$REL plan 0.2.0 --date 2026-03-04 >"$T/do" 2>&1; ct=$(tok < "$T/do")
[ -n "$ct" ] || no "(setup) release plan: $(cat "$T/do")"
chk "$ct" "release plan" "rel:0.2.0" "project:name kind:label version:name date:label keep:label allow-empty:label branch:ref base:ref head:sha master:sha second:ref steps:label start-plan:sha fix-paths:path"
st=$(jq -r '.lines[] | select(.label == "start-plan") | .value' "$PLANS/$ct.json")
chk "$st" "release start" "rel:0.2.0" "project:name kind:label branch:ref base:ref head:sha version:name date:label files:path" "release start (planned by the cut)"
[ "$(jq -r '[.lines[] | select(.label == "files") | .value] | join(",")' "$PLANS/$st.json")" = "CHANGELOG.md,VERSION" ] && ok "the files of the start are one entry each" || no "start files: $(jq -c '.lines' "$PLANS/$st.json")"
$REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "go ahead" >/dev/null 2>&1; $REL start 0.2.0 --plan "$ct" >/dev/null 2>&1
git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null || no "(setup) the cut did not start the release: $($REL status 0.2.0 2>&1)"
pt=$($REL push 0.2.0 | tok)
chk "$pt" "release push" "rel:0.2.0" "project:name branch:ref head:sha"
git -C "$R" push -q origin release/0.2.0 2>/dev/null
mkproj relj
$REL verify 0.3.0 >/dev/null 2>&1
js=$($REL start 0.3.0 --date 2026-03-05 | tok)
chk "$js" "release start" "relj:0.3.0" "project:name kind:label branch:ref base:ref head:sha version:name date:label files:path"

# ---------------------------------------------------------------------------------------------------------------------------- the old readers still work
# a token whose plan moved still says which labels: plan-stale names them from the basis key
mkproj stale
$F start sa >/dev/null 2>&1; task t1 feature/sa; $F merge sa agent/t1 >/dev/null 2>&1; $F verify sa >/dev/null 2>&1
old=$($F finish sa | tok); $F finish sa --keep >/dev/null 2>&1
$F finish sa --keep --plan "$old" --approved go >"$T/do" 2>"$T/de"; rc=$?
[ "$rc" = 1 ] && grep -q '"code":"plan-stale".*"detail":"moved=keep token=' "$T/de" && ok "plan-stale still names the label that moved (keep), read from the basis key" || no "plan-stale: rc=$rc $(cat "$T/de")"
exit $fail
