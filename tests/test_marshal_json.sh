#!/usr/bin/env bash
# The documents of qargi marshal status, check and handoff (--json), and the refusals of the three verbs: each output is valid
# against its registry file (lib/kinds), a marshal refusal keeps its own exit status and prints its contract line, and a call
# that is switched to read only (--no-write) changes and fetches nothing.
# Time is injected with QARGI_MARSHAL_NOW (the wall clock) and QARGI_MARSHAL_MONO (the monotonic clock of the refs backend); the
# remote is a scratch bare repository; nothing leaves the temporary directory. check --json is reached through QARGI_NO_JSON_WRAP=1
# until the command table declares the option.
# Run: tests/test_marshal_json.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TOOL=$PWD
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
unset GIT_TERMINAL_PROMPT
export TMPDIR=$T/tmp; mkdir -p "$TMPDIR"
JK="python3 -I $TOOL/lib/jsonkind.py"
NOW=1000000

# --- the local backend: a project with a few feature branches, its own home, conf and state
L0=$T/l
mkdir -p "$L0/home" "$L0/c/projects" "$L0/s/features"
R=$L0/app; make_repo "$R"
for n in f1 f2 f3 f4 f5 f6; do git -C "$R" branch "feature/$n" develop; done
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, models:{provider:{local:"claude-code",cloud:"claude-platform"}}, test_command:"true"}' > "$L0/c/projects/app.json"
# L ARGS...: qargi on the local project at the clock $NOW; stdout and stderr in $T/o and $T/e, the exit status returned
L() { env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op QARGI_NO_JSON_WRAP=1 "$DA" "$@" >"$T/o" 2>"$T/e"; }
LREC() { echo "$L0/s/features/app-$1.json"; }

# --- the refs backend: a scratch origin and one machine
ORIGIN=$T/origin.git
make_origin "$ORIGIN"
make_machine a
for n in r1 r2; do git -C "$T/m/a/app" branch "feature/$n" develop; done
# XE MACHINE [VAR=val...] ARGS...: qargi as that machine; output in $T/o and $T/e, the exit status returned
XE() {
  local m=$1; shift; local -a ev=()
  while [[ ${1:-} =~ ^[A-Z_]+= ]]; do ev+=("$1"); shift; done
  env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op QARGI_NO_JSON_WRAP=1 "${ev[@]}" "$DA" "$@" >"$T/o" 2>"$T/e"
}
WORDS="the shared refs are fine for this project"
en() { local tk; XE "$1" marshal enable; tk=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o"); XE "$1" marshal enable --plan "$tk" --approved "$WORDS"; }
en a || no "setup: enable the shared refs on machine a: $(out)"

# valid KIND [FILE]: the document (FILE, else $T/o) is valid against the registry file of KIND
valid() { local f=${2:-$T/o}; $JK validate "$1" "$f" 2>"$T/v"; }
# refusal CODE RC: the last call exited RC, wrote nothing to stdout and has one valid contract line on stderr of CODE and exit RC, and the
# plain sentence of the marshal follows the block
refusal() {
  local code=$1 rc=$2 line
  [ "$RC" = "$rc" ] || { echo "exit $RC, not $rc"; return 1; }
  [ ! -s "$T/o" ] || { echo "stdout is not empty"; return 1; }
  line=$(grep -m1 '^qargi-refusal/1 ' "$T/e")
  case $line in 'qargi-refusal/1 {'*) ;; *) echo "no contract line on stderr: $line"; return 1;; esac
  printf '%s\n' "${line#qargi-refusal/1 }" | $JK validate qargi-refusal - 2>"$T/v" || { echo "the contract line is not valid: $(cat "$T/v")"; return 1; }
  [ "$(printf '%s\n' "${line#qargi-refusal/1 }" | jq -r '[.code, .exit] | @tsv')" = "$(printf '%s\t%s' "$code" "$rc")" ] || { echo "not code $code exit $rc: $line"; return 1; }
  [ "$(grep -c '^qargi-refusal/1 ' "$T/e")" = 1 ] && grep -q '^qargi: refused \[' "$T/e" && grep -v '^qargi: refused \[' "$T/e" | grep -q '^qargi: ' || { echo "the block and the sentence are not both there: $(cat "$T/e")"; return 1; }
  ! grep -q '^Traceback' "$T/e" || { echo "a traceback"; return 1; }
}
# call ARGS...: runs "$@" and keeps its status in RC
call() { "$@"; RC=$?; }

# ================================================================ (1) every coded refusal of the three verbs: empty stdout, a valid line, the right status
call L marshal claim f1 --as alice --goal "one"
[ "$RC" = 0 ] && ok "setup: alice leads f1" || no "setup: claim f1 ($RC): $(out)"
NOW=$((NOW + 10))
call L marshal check f1 --as bob
refusal marshal-feature-held 1 && ok "check: a feature another live lead holds is a refusal (marshal-feature-held, exit 1)" || no "check held: $(refusal marshal-feature-held 1; out)"
call L marshal check nosuch --as bob
refusal marshal-feature-unknown 1 && ok "check: no such feature is marshal-feature-unknown, exit 1, no document" || no "check unknown: $(refusal marshal-feature-unknown 1; out)"
call L marshal status nosuch --json
refusal marshal-feature-unknown 1 && ok "status --json: no such feature is marshal-feature-unknown, exit 1, no document" || no "status unknown: $(refusal marshal-feature-unknown 1; out)"
call L marshal status nosuch
refusal marshal-feature-unknown 1 && ok "status (text): no such feature carries the line too" || no "status text unknown: $(out)"
call L marshal handoff nosuch --json
refusal marshal-feature-unknown 1 && ok "handoff --json: no such feature is marshal-feature-unknown, exit 1, no document" || no "handoff unknown: $(refusal marshal-feature-unknown 1; out)"
: > "$T/exists"
call L marshal handoff --json --write "$T/exists"
refusal marshal-handoff-file 1 && ok "handoff --write: a file that exists is marshal-handoff-file, exit 1" || no "handoff write exists: $(refusal marshal-handoff-file 1; out)"
call L marshal handoff --write "$R/note.json"
refusal marshal-handoff-file 1 && [ ! -e "$R/note.json" ] && ok "handoff --write: a file inside a repository is marshal-handoff-file, and nothing is made" || no "handoff write in repo: $(out)"
call L marshal check 'Not_A_Name'
refusal marshal-refused 1 && ok "check: not a feature name is the generic code (marshal-refused)" || no "check bad name: $(refusal marshal-refused 1; out)"
mkdir -p "$L0/s/marshal"; echo '{"backend": "nowhere"}' > "$L0/s/marshal/app.enabled"
call L marshal status --all --json
refusal marshal-refused 1 && ok "status --json: an unknown backend in the switch file is the generic code" || no "status bad switch: $(refusal marshal-refused 1; out)"
echo 'not json' > "$L0/s/marshal/app.enabled"
call L marshal check f2
refusal marshal-refused 1 && ok "check: an unreadable switch file is the generic code" || no "check bad switch: $(refusal marshal-refused 1; out)"
echo '{"backend": "local", "integrity": "sometimes"}' > "$L0/s/marshal/app.enabled"
call L marshal check f2
refusal marshal-refused 1 && ok "check: an unknown integrity in the switch file is the generic code" || no "check bad integrity: $(refusal marshal-refused 1; out)"
rm -f "$L0/s/marshal/app.enabled"
printf 'not json' > "$(LREC f2)"
call L marshal check f2
refusal marshal-refused 1 && ok "check: a record that cannot be read is the generic code" || no "check bad record: $(refusal marshal-refused 1; out)"
echo '[1]' > "$(LREC f2)"
call L marshal status f2 --json
refusal marshal-refused 1 && ok "status --json: a record that is not an object is the generic code" || no "status non-object record: $(refusal marshal-refused 1; out)"
rm -f "$(LREC f2)"
NOW=soon; call L marshal check f2; NOW=$((1000000 + 10))
refusal marshal-refused 1 && ok "check: a QARGI_MARSHAL_NOW that is no number is the generic code" || no "check bad clock: $(refusal marshal-refused 1; out)"
call L marshal check f2 --as 'bad id!'
refusal marshal-refused 1 && ok "check: a lead identity that is not valid is the generic code" || no "check bad identity: $(refusal marshal-refused 1; out)"

# the remote of the shared records cannot be asked: the claim is made first, then the origin goes away
call XE a marshal claim r1 --as alice --goal "shared"
[ "$RC" = 0 ] && ok "setup: alice claims r1 on the shared refs" || no "setup: claim r1 on the refs backend ($RC): $(out)"
mv "$ORIGIN" "$ORIGIN.gone"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice
refusal marshal-remote-unreachable 3 && ok "check: a remote that cannot be asked is marshal-remote-unreachable, exit 3, no document" || no "check unreachable: $(refusal marshal-remote-unreachable 3; out)"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check
refusal marshal-remote-unreachable 3 && ok "check with no NAME: the same, exit 3" || no "check all unreachable: $(refusal marshal-remote-unreachable 3; out)"
mv "$ORIGIN.gone" "$ORIGIN"

# ================================================================ (2) a refusal keeps its status whatever happens while it is rendered
# a lead id that is 5000 characters long, and one that holds a newline: the record is edited by hand (the marshal itself takes neither)
long=$(head -c 5000 /dev/zero | tr '\0' 'x')
for kind in long newline; do
  if [ $kind = long ]; then id=$long; else id=$'ali\nce'; fi
  jq --arg id "$id" '.lead.id = $id' "$(LREC f1)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f1)"
  call L marshal check f1 --as bob
  [ "$RC" = 1 ] && [ ! -s "$T/o" ] && ! grep -q '^Traceback' "$T/e" && grep -m1 '^qargi-refusal/1 ' "$T/e" | grep -q '^qargi-refusal/1 {"code":"marshal-feature-held"' \
    && ok "check: a held feature whose lead id is $kind still exits 1 with its contract line (the id is left out of the block)" || no "check held, $kind id: rc=$RC $(head -c 600 "$T/e")"
  [ "$(grep -c '^qargi-refusal/1 ' "$T/e")" = 1 ] && ok "check: a lead id that is $kind forges no second contract line" || no "check held, $kind id forges a line: $(head -c 800 "$T/e")"
done
# the flow verbs end on status 1 of the gate: feature merge refuses and moves nothing
git -C "$R" branch agent/t1 develop
tipf=$(git -C "$R" rev-parse feature/f1)
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_LEAD=bob "$DA" feature merge f1 agent/t1 >"$T/o" 2>"$T/e"; RC=$?
[ "$RC" = 1 ] && [ "$(git -C "$R" rev-parse feature/f1)" = "$tipf" ] && ! grep -q '^Traceback' "$T/e" && ok "feature merge: a feature whose lead id is a newline is still refused (exit 1) and does not move" || no "feature merge, newline id: rc=$RC $(head -c 600 "$T/e")"
jq --arg id "$long" '.lead.id = $id' "$(LREC f1)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f1)"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_LEAD=bob "$DA" feature merge f1 agent/t1 >"$T/o" 2>"$T/e"; RC=$?
[ "$RC" = 1 ] && [ "$(git -C "$R" rev-parse feature/f1)" = "$tipf" ] && ! grep -q '^Traceback' "$T/e" && ok "feature merge: a feature whose lead id is 5000 characters long is still refused (exit 1) and does not move" || no "feature merge, long id: rc=$RC $(head -c 600 "$T/e")"
jq '.lead.id = "alice"' "$(LREC f1)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f1)"

# the catalogue cannot be read: a scratch copy of the tool; the refusal is the plain line, exit 1, no traceback
TC=$T/tool; mkdir -p "$TC"; cp -a "$TOOL/bin" "$TOOL/lib" "$TOOL/VERSION" "$TC/"
for how in unreadable broken missing; do
  case $how in
    unreadable) chmod 000 "$TC/lib/refusals.json";;
    broken) chmod 644 "$TC/lib/refusals.json"; echo '{"codes": [' > "$TC/lib/refusals.json";;
    missing) rm -f "$TC/lib/refusals.json";;
  esac
  env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" "$TC/bin/qargi" marshal check f1 --as bob >"$T/o" 2>"$T/e"; RC=$?
  [ "$RC" = 1 ] && ! grep -q 'Traceback' "$T/e" && grep -q '^qargi: feature f1 is led by alice' "$T/e" && ! grep -q 'qargi-refusal/1' "$T/e" \
    && ok "check: with the catalogue $how a held feature is still exit 1, the plain line and no traceback" || no "check held, catalogue $how: rc=$RC $(head -c 600 "$T/e")"
done


# ================================================================ (2b) the same refusals of check --json: no document, the line, the status
call L marshal check nosuch --as bob --json
refusal marshal-feature-unknown 1 && ok "check --json: no such feature is marshal-feature-unknown, exit 1, no document" || no "check --json unknown: $(refusal marshal-feature-unknown 1; out)"
call L marshal check f1 --as bob --json
refusal marshal-feature-held 1 && ok "check --json: a feature another live lead holds is marshal-feature-held, exit 1, no document" || no "check --json held: $(refusal marshal-feature-held 1; out)"
call L marshal check 'Not_A_Name' --json
refusal marshal-refused 1 && ok "check --json: not a feature name is the generic code" || no "check --json bad name: $(refusal marshal-refused 1; out)"
for kind in long newline; do
  if [ $kind = long ]; then id=$long; else id=$'ali\nce'; fi
  jq --arg id "$id" '.lead.id = $id' "$(LREC f1)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f1)"
  call L marshal check f1 --as bob --json
  refusal marshal-feature-held 1 && ok "check --json: a held feature whose lead id is $kind is still exit 1 with its line and no document" || no "check --json held, $kind id: $(refusal marshal-feature-held 1; head -c 500 "$T/e")"
done
jq '.lead.id = "alice"' "$(LREC f1)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f1)"
mv "$ORIGIN" "$ORIGIN.gone"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice --json
refusal marshal-remote-unreachable 3 && ok "check --json: a remote that cannot be asked is marshal-remote-unreachable, exit 3, no document" || no "check --json unreachable: $(refusal marshal-remote-unreachable 3; out)"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check --json
refusal marshal-remote-unreachable 3 && ok "check --json with no NAME: the same, exit 3" || no "check --json all unreachable: $(refusal marshal-remote-unreachable 3; out)"
mv "$ORIGIN.gone" "$ORIGIN"

# ================================================================ (3) status --json: one shape, with or without NAME, on both backends
NOW=$((1000000 + 20))
call L marshal status --all --json
[ "$RC" = 0 ] && valid qargi-marshal-status && ok "status --all --json (local): a valid document" || no "status --all --json: rc=$RC $(cat "$T/v"; head -c 400 "$T/e")"
jq -e '.kind == "qargi-marshal-status" and .schema == 1 and .backend == "local" and .remote == "none" and (.features | length) == 6 and (.agent_unattributed | type) == "array"' "$T/o" >/dev/null \
  && ok "status --all --json (local): backend local, remote none, one row for each open feature" || no "status --all --json fields: $(head -c 600 "$T/o")"
jq -e '[.features[] | select(.feature == "f1")] | .[0] | .lease == "live" and .lease_clock == "wall" and .minutes_since_renewal == 0 and .lead.id == "alice" and (.tasks | type) == "array" and (.overlap | type) == "object"' "$T/o" >/dev/null \
  && ok "status --all --json (local): a row has the lead, a live lease on the wall clock and the derived lists" || no "status row f1: $(jq -c '.features[] | select(.feature == "f1")' "$T/o")"
call L marshal status f1 --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.kind == "qargi-marshal-status" and (.features | length) == 1 and .features[0].feature == "f1" and (has("lead") | not) and (.agent_unattributed | type) == "array"' "$T/o" >/dev/null \
  && ok "status NAME --json: the same shape with one row (no bare feature object any more)" || no "status f1 --json: rc=$RC $(cat "$T/v"; head -c 400 "$T/o")"
call L marshal status --all --history --json
[ "$RC" = 0 ] && valid qargi-marshal-status && ok "status --all --history --json: a valid document" || no "status --history --json: rc=$RC $(cat "$T/v")"
# a run of the lead's registry: one whose directory exists and one that is gone
mkdir -p "$T/rundir"
printf '%s\n' '{"run":"'"$T"'/rundir","slug":"t1","ability":"build","base":"feature/f1","started":"2026-01-01T00:00:00Z"}' '{"run":"'"$T"'/gone","slug":"t2","ability":"review","base":"feature/f1","started":"2026-01-02T00:00:00Z"}' > "$L0/s/local-runs.jsonl"
call L marshal status f1 --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.features[0].tasks | length == 2 and .[0].directory_gone == false and .[1].directory_gone == true and (.[1].state | test("directory gone"))' "$T/o" >/dev/null \
  && ok "status --json: a task has directory_gone, true for a run whose directory is gone" || no "status tasks: rc=$RC $(jq -c '.features[0].tasks' "$T/o")"
rm -f "$L0/s/local-runs.jsonl"

call XE a QARGI_MARSHAL_MONO=1000.7 marshal status --all --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.backend == "refs" and .remote == "checked"' "$T/o" >/dev/null && ok "status --all --json (refs): a valid document, backend refs, remote checked" || no "status refs: rc=$RC $(cat "$T/v"; head -c 400 "$T/o")"
call XE a QARGI_MARSHAL_MONO=1500.3 marshal status --all --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '[.features[] | select(.feature == "r1")] | .[0] | .lease_clock == "observed-here" and .lead.id == "alice"' "$T/o" >/dev/null \
  && grep -Eq '"minutes_since_renewal": 8,' "$T/o" && ok "status --json (refs): with the monotonic clock held minutes_since_renewal is the integer 8 (it was a float), lease_clock observed-here" || no "status refs minutes: rc=$RC $(cat "$T/v"; jq -c '.features[] | select(.feature == "r1")' "$T/o")"
call XE a marshal status --all --json --no-fetch
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.remote == "not-asked" and .backend == "refs"' "$T/o" >/dev/null && ok "status --json --no-fetch (refs): remote not-asked" || no "status refs --no-fetch: rc=$RC $(head -c 300 "$T/o")"
mv "$ORIGIN" "$ORIGIN.gone"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal status r1 --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.remote == "unchecked" and .features[0].feature == "r1"' "$T/o" >/dev/null && grep -q 'remote not checked' "$T/e" \
  && ok "status --json (refs, remote unreachable): exit 0 from the cache, remote unchecked, the notice on stderr" || no "status refs unreachable: rc=$RC $(cat "$T/v"; head -c 300 "$T/o"; head -c 300 "$T/e")"
mv "$ORIGIN.gone" "$ORIGIN"

# ================================================================ (4) a record that holds a value the document does not allow: exit 70, no document; the text form is as before
call L marshal claim f4 --as alice --goal "text"
call L marshal status f4
cp "$T/o" "$T/text.before"; [ "$RC" = 0 ] || no "setup: status f4 (text) rc=$RC"
cp "$(LREC f4)" "$T/f4.good"
jq '.rev = 1.5' "$(LREC f4)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f4)"
call L marshal status f4 --json
[ "$RC" = 70 ] && [ ! -s "$T/o" ] && grep -q '^qargi: defect: ' "$T/e" && grep -q 'rev' "$T/e" && ! grep -q Traceback "$T/e" && [ "$(wc -l < "$T/e")" = 1 ] \
  && ok "status --json: a record with \"rev\": 1.5 is exit 70 with one line that names the path, and no document" || no "status rev 1.5: rc=$RC $(cat "$T/o" "$T/e")"
call L marshal status f4
[ "$RC" = 0 ] && cmp -s "$T/o" "$T/text.before" && ok "status (text): the same record gives the same text as before" || no "status text with rev 1.5: rc=$RC $(diff "$T/text.before" "$T/o")"
call L marshal status --all --json
[ "$RC" = 70 ] && [ ! -s "$T/o" ] && ok "status --all --json: one bad row makes the whole document a defect (exit 70)" || no "status --all with a bad row: rc=$RC $(head -c 300 "$T/o")"
sed -i 's/"rev": [0-9.]*/"rev": NaN/' "$(LREC f4)"
call L marshal status f4 --json
[ "$RC" = 70 ] && [ ! -s "$T/o" ] && ! grep -q Traceback "$T/e" && ok "status --json: a record with \"rev\": NaN is exit 70, never a document with NaN in it" || no "status NaN: rc=$RC $(cat "$T/o" "$T/e")"
cp "$T/f4.good" "$(LREC f4)"; jq '.renewed_at = 12' "$(LREC f4)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f4)"
call L marshal status f4 --json
[ "$RC" = 70 ] && ok "status --json: a renewed_at that is a number is exit 70" || no "status renewed_at 12: rc=$RC $(cat "$T/o" "$T/e")"
jq '.renewed_at = "2001-09-09T01:46:40Z"' "$(LREC f4)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f4)"
call L marshal status f4 --json
[ "$RC" = 0 ] && valid qargi-marshal-status && ok "status --json: the record put right gives a document again" || no "status f4 repaired: rc=$RC $(cat "$T/o" "$T/e")"

# ================================================================ (5) a stdout that cannot take the document: a failure with a plain line, never exit 0
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_NO_JSON_WRAP=1 "$DA" marshal status --all --json >&- 2>"$T/e"; RC=$?
[ "$RC" != 0 ] && ! grep -q Traceback "$T/e" && ok "status --json with stdout closed: a non-zero exit, no traceback ($RC)" || no "status closed stdout: rc=$RC $(cat "$T/e")"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_NO_JSON_WRAP=1 "$DA" marshal status --all --json >/dev/full 2>"$T/e"; RC=$?
[ "$RC" = 1 ] && [ "$(wc -l < "$T/e")" = 1 ] && grep -q '^qargi: cannot write the document' "$T/e" && ok "status --json to a full disk: exit 1 and one plain line" || no "status full stdout: rc=$RC $(cat "$T/e")"

# ================================================================ (6) check --json: the answer, the lead and the warnings; one row each without NAME
NOW=$((1000000 + 30))
call L marshal check f1 --as alice --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.kind == "qargi-marshal-check" and .backend == "local" and .remote == "none" and .feature == "f1" and .answer == "yours" and .lead == null and .warnings == [] and (has("features") | not)' "$T/o" >/dev/null \
  && ok "check NAME --json: the caller leads the feature (answer yours, no lead, no warnings)" || no "check yours: rc=$RC $(cat "$T/v"; head -c 400 "$T/o")"
call L marshal check f1 --as alice
[ "$RC" = 0 ] && [ "$(cat "$T/o")" = yours ] && ok "check NAME (text): still the one word on stdout" || no "check text yours: rc=$RC $(out)"
call L marshal check f3 --as bob --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.answer == "free" and .lead == null and (.warnings | length) == 1 and (.warnings[0] | test("has no lead"))' "$T/o" >/dev/null && grep -q 'warning: feature f3 has no lead' "$T/e" \
  && ok "check NAME --json: a feature with no lead is free, the warning is in the document and on stderr" || no "check free: rc=$RC $(cat "$T/v"; head -c 400 "$T/o"; cat "$T/e")"
NOW=$((1000000 + 30 + 900))
call L marshal check f1 --as bob --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.answer == "free-stale" and .lead.id == "alice" and .lead.user != null and (.warnings | length) >= 1' "$T/o" >/dev/null \
  && ok "check NAME --json: a feature whose lead is stale is free-stale and the document holds that lead" || no "check free-stale: rc=$RC $(cat "$T/v"; head -c 500 "$T/o")"
call L marshal check f1 --as bob
[ "$RC" = 0 ] && [ "$(cat "$T/o")" = "free (the lead alice is stale)" ] && ok "check NAME (text): the stale lead is said as before" || no "check text stale: rc=$RC $(out)"
call L marshal check --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.feature == null and .answer == null and .lead == null and .warnings == [] and (.features | length) == 6 and ([.features[] | has("tasks") or has("overlap")] | any | not) and ([.features[] | .warnings | type] | all(. == "array"))' "$T/o" >/dev/null \
  && ok "check --json with no NAME: feature and answer null, one row for each open feature, each with its own warnings" || no "check all: rc=$RC $(cat "$T/v"; head -c 500 "$T/o")"
jq -e '[.features[] | select(.feature == "f1")] | .[0] | .lease == "stale" and .lease_clock == "wall" and (.warnings | length) >= 1' "$T/o" >/dev/null && ok "check --json with no NAME: the row of a stale lead says stale and carries its warning" || no "check all row f1: $(jq -c '.features[0]' "$T/o")"
call L marshal check
[ "$RC" = 0 ] && grep -q '^f1  lead=stale(alice)' "$T/o" && ok "check (text) with no NAME: the brief lines as before" || no "check text all: rc=$RC $(out)"

# the remote of the shared records: checked, not asked, unchecked
call XE a QARGI_MARSHAL_MONO=2000 marshal check r1 --as alice --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.backend == "refs" and .remote == "checked" and .answer == "yours"' "$T/o" >/dev/null && ok "check --json (refs): remote checked" || no "check refs checked: rc=$RC $(cat "$T/v"; head -c 300 "$T/o"; cat "$T/e")"
call XE a marshal check r1 --as alice --json --no-fetch
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.remote == "not-asked"' "$T/o" >/dev/null && ok "check --json --no-fetch (refs): remote not-asked" || no "check refs not-asked: rc=$RC $(head -c 300 "$T/o"; cat "$T/e")"
mv "$ORIGIN" "$ORIGIN.gone"
rm -f "$T/m/a/s/audit.log"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice --json --assume-unreachable-ok
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.remote == "unchecked" and .answer == "yours"' "$T/o" >/dev/null && grep -q '"verb":"marshal:unreachable-ok"' "$T/m/a/s/audit.log" \
  && ok "check --json --assume-unreachable-ok (refs, remote unreachable): exit 0 from the cache, remote unchecked, one audit line" || no "check refs unchecked: rc=$RC $(head -c 300 "$T/o"; cat "$T/e"; cat "$T/m/a/s/audit.log" 2>&1)"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice --json
refusal marshal-remote-unreachable 3 && ok "check --json (refs, remote unreachable, no override): exit 3, the line, no document" || no "check refs unreachable: $(refusal marshal-remote-unreachable 3; out)"
mv "$ORIGIN.gone" "$ORIGIN"

# ================================================================ (7) handoff --json: remote, backend_fallback, integers, the write
NOW=$((1000000 + 40))
call L marshal handoff --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.kind == "qargi-handoff" and .backend == "local" and .remote == "none" and .backend_fallback == false and .truncated == false' "$T/o" >/dev/null \
  && ok "handoff --json (local): a valid document, remote none, no fallback" || no "handoff local: rc=$RC $(cat "$T/v"; head -c 400 "$T/e")"
call L marshal handoff f1 --json
[ "$RC" = 0 ] && valid qargi-handoff && [ "$(jq '.features | length' "$T/o")" = 1 ] && ok "handoff NAME --json (local): a valid document with one feature" || no "handoff f1: rc=$RC $(cat "$T/v")"
jq '.models = {provider: {local: "claude-code", cloud: "claude-platform"}}' "$T/m/a/c/projects/app.json" > "$T/m/a/c/p.tmp" && mv "$T/m/a/c/p.tmp" "$T/m/a/c/projects/app.json"
call XE a QARGI_MARSHAL_MONO=3000 marshal handoff --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.backend == "refs" and .remote == "not-asked" and .backend_fallback == false' "$T/o" >/dev/null \
  && ok "handoff --json (refs): a valid document, remote not-asked (the handoff never fetches), no fallback" || no "handoff refs: rc=$RC $(cat "$T/v"; head -c 400 "$T/e")"
call XE a QARGI_MARSHAL_MONO=3500.4 marshal handoff r1 --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.features[0].record.minutes_since_renewal | type == "number"' "$T/o" >/dev/null \
  && ! grep -Eq '"minutes_since_renewal": [0-9]+\.[0-9]' "$T/o" && ok "handoff --json (refs): minutes_since_renewal is an integer with the monotonic clock held" || no "handoff refs minutes: rc=$RC $(cat "$T/v"; jq -c '.features[0].record' "$T/o")"
# the shared records cannot be read: the local records are shown and the field says so
cp -a "$T/m/a/s" "$T/s2"; jq '.integrity = "advisory"' "$T/s2/marshal/app.enabled" > "$T/s2/sw.tmp" && mv "$T/s2/sw.tmp" "$T/s2/marshal/app.enabled"; echo garbage > "$T/s2/features/.accepted-app.json"
call XE a QARGI_STATE="$T/s2" marshal handoff --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.backend == "local" and .backend_fallback == true and .remote == "none" and ([.notes[] | select(test("shared records cannot be read"))] | length) == 1' "$T/o" >/dev/null \
  && ok "handoff --json: the shared records cannot be read: backend local, backend_fallback true, the sentence in notes" || no "handoff fallback: rc=$RC $(cat "$T/v"; jq -c '[.backend, .backend_fallback, .remote, .notes]' "$T/o")"
echo '{"backend": "refs", "remote": "origin", "integrity": "sometimes"}' > "$T/s2/marshal/app.enabled"
call XE a QARGI_STATE="$T/s2" marshal handoff --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.backend == "local" and .backend_fallback == true and ([.notes[] | select(test("switch cannot be used"))] | length) == 1' "$T/o" >/dev/null \
  && ok "handoff --json: a switch file that cannot be used is a fallback too" || no "handoff bad switch: rc=$RC $(jq -c '[.backend, .backend_fallback, .notes]' "$T/o")"
# the environment record is read only for the types the document declares
mkdir -p "$L0/s/env"
cat > "$L0/s/env/app.json" <<'ENV'
{"check": {"verdict": "ok", "exit": 1.5, "missing": 2, "expected": true, "time": "2026-01-01T00:00:00Z", "head": "abc", "doctor_command": 5, "builtin_minimum": 1.0},
 "apply": {"exit": 0, "time": 7, "command": "make bootstrap", "head": "abc", "allow_root": false}}
ENV
call L marshal handoff --json
[ "$RC" = 0 ] && valid qargi-handoff && jq -e '.environment.check == {"verdict": "ok", "missing": 2, "time": "2026-01-01T00:00:00Z", "head": "abc", "at_head": false} and .environment.apply == {"exit": 0, "command": "make bootstrap", "head": "abc", "allow_root": false, "at_head": false}' "$T/o" >/dev/null \
  && ok "handoff --json: a float, a boolean for a number or a number for text in the env record is left out, the rest is kept" || no "handoff env: rc=$RC $(cat "$T/v"; jq -c '.environment' "$T/o")"
rm -rf "$L0/s/env"
# a record that holds a value the document does not allow: exit 70, no document; the text form is as before
jq '.rev = 1.5' "$(LREC f4)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f4)"
call L marshal handoff --json
[ "$RC" = 70 ] && [ ! -s "$T/o" ] && grep -q '^qargi: defect: ' "$T/e" && ! grep -q Traceback "$T/e" && ok "handoff --json: a record with \"rev\": 1.5 is exit 70 and no document" || no "handoff rev 1.5: rc=$RC $(head -c 300 "$T/o"; cat "$T/e")"
call L marshal handoff
[ "$RC" = 0 ] && grep -q '^== ' "$T/o" && ok "handoff (text): the same record gives the note as before" || no "handoff text rev 1.5: rc=$RC $(out | head -c 300)"
jq '.rev = 1' "$(LREC f4)" > "$T/rec.tmp" && mv "$T/rec.tmp" "$(LREC f4)"

# --json --write: the document on stdout first, then the file, then the sentence on stderr
W=$T/scratch; mkdir -p "$W"
call L marshal handoff --json --write "$W/note.json"
[ "$RC" = 0 ] && valid qargi-handoff && cmp -s "$T/o" "$W/note.json" && [ "$(stat -c %a "$W/note.json")" = 600 ] && grep -q "^wrote $W/note.json " "$T/e" && ! grep -q wrote "$T/o" \
  && ok "handoff --json --write: stdout is the document alone, the file holds the same bytes (mode 600), the sentence is on stderr" || no "handoff json write: rc=$RC $(cat "$T/v"; head -c 300 "$T/e")"
call L marshal handoff --write "$W/note.txt"
[ "$RC" = 0 ] && grep -q "^wrote $W/note.txt " "$T/o" && [ -s "$W/note.txt" ] && ok "handoff --write (text): the sentence stays on stdout" || no "handoff text write: rc=$RC $(out)"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" "$DA" marshal handoff --json --write "$W/closed.json" >&- 2>"$T/e"; RC=$?
[ "$RC" != 0 ] && [ ! -e "$W/closed.json" ] && ! grep -q Traceback "$T/e" && ok "handoff --json --write with stdout closed: a non-zero exit and no file" || no "handoff closed stdout: rc=$RC file=$(ls "$W") $(cat "$T/e")"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" "$DA" marshal handoff --json --write "$W/full.json" >/dev/full 2>"$T/e"; RC=$?
[ "$RC" = 1 ] && [ ! -e "$W/full.json" ] && grep -q '^qargi: cannot write the document' "$T/e" && ok "handoff --json --write to a full stdout: exit 1 and no file" || no "handoff full stdout: rc=$RC file=$(ls "$W") $(cat "$T/e")"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" "$DA" marshal handoff --json >&- 2>"$T/e"; RC=$?
[ "$RC" != 0 ] && ok "handoff --json with stdout closed: a non-zero exit ($RC)" || no "handoff --json closed: rc=$RC $(cat "$T/e")"
# the file cannot be made after the document was written: a refusal naming the file, exit 1, and the document stays on stdout
mkdir -p "$W/ro"; chmod 555 "$W/ro"
call L marshal handoff --json --write "$W/ro/note.json"
if [ "$(id -u)" != 0 ]; then
  [ "$RC" = 1 ] && jq -e '.kind == "qargi-handoff"' "$T/o" >/dev/null && grep -q 'marshal-handoff-file' "$T/e" && grep -q "ro/note.json" "$T/e" \
    && ok "handoff --json --write: a file that cannot be made after the document was written is a refusal (exit 1) naming the file" || no "handoff write fails late: rc=$RC $(head -c 200 "$T/o"; cat "$T/e")"
fi
chmod 755 "$W/ro"

# ================================================================ (8) --no-write: nothing is written and nothing is fetched
# a local record whose branch is gone: status and check mark it abandoned (and write the record); with --no-write the record stays byte for byte
NOW=$((1000000 + 50))
call L marshal claim f6 --as alice --goal "branch will go"
git -C "$R" branch -q -D feature/f6
cp "$(LREC f6)" "$T/f6.before"; rm -f "$L0/s/audit.log"; cp -a "$L0/s/features" "$T/features.before"
call L marshal status f6 --no-write --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.features[0].status == "active" and .features[0].ghost == false and .features[0].branch == false and .remote == "none"' "$T/o" >/dev/null \
  && cmp -s "$(LREC f6)" "$T/f6.before" && ok "status NAME --no-write: a record whose branch is gone is shown as it is and stays byte for byte" || no "status --no-write: rc=$RC $(cat "$T/v"; head -c 300 "$T/o")"
call L marshal status --all --no-write --json
[ "$RC" = 0 ] && valid qargi-marshal-status && cmp -s "$(LREC f6)" "$T/f6.before" && ok "status --all --no-write: the same" || no "status --all --no-write: rc=$RC $(cat "$T/v")"
call L marshal status --all --no-write
[ "$RC" = 0 ] && cmp -s "$(LREC f6)" "$T/f6.before" && ok "status --all --no-write (text): the same" || no "status --all --no-write text: rc=$RC $(out)"
call L marshal check f6 --as alice --no-write --json
[ "$RC" = 0 ] && valid qargi-marshal-check && cmp -s "$(LREC f6)" "$T/f6.before" && ok "check NAME --no-write --json: the record stays byte for byte" || no "check --no-write: rc=$RC $(cat "$T/v"; head -c 300 "$T/e")"
call L marshal check --no-write --assume-unreachable-ok --json
[ "$RC" = 0 ] && valid qargi-marshal-check && cmp -s "$(LREC f6)" "$T/f6.before" && [ ! -e "$L0/s/audit.log" ] && diff -r "$T/features.before" "$L0/s/features" >/dev/null && ok "check --no-write --assume-unreachable-ok: no audit line, and nothing under the records changed" || no "check --no-write --assume-unreachable-ok: rc=$RC $(cat "$T/v"; ls -la "$L0/s")"
call L marshal status f6 --json
[ "$RC" = 0 ] && jq -e '.features[0].status == "abandoned" and .features[0].ghost == true' "$T/o" >/dev/null && ! cmp -s "$(LREC f6)" "$T/f6.before" \
  && ok "status NAME (without --no-write): the default is unchanged, the record is marked abandoned" || no "status f6 default: rc=$RC $(head -c 300 "$T/o")"
git -C "$R" branch -q feature/f6 develop

# the shared records: nothing fetched, no cache written, the answer says not-asked
OBS=$T/m/a/s/features/.observed-app.json
XE a QARGI_MARSHAL_MONO=5000 marshal status --all --brief >/dev/null
cp "$OBS" "$T/obs.before"; cp -a "$T/m/a/s/features" "$T/afeatures.before"
mv "$ORIGIN" "$ORIGIN.gone"
call XE a QARGI_MARSHAL_MONO=9000 QARGI_REMOTE_TIMEOUT=2 marshal status --all --no-write --json
[ "$RC" = 0 ] && valid qargi-marshal-status && jq -e '.remote == "not-asked" and .backend == "refs"' "$T/o" >/dev/null && ! grep -q 'remote not checked' "$T/e" && cmp -s "$OBS" "$T/obs.before" \
  && ok "status --no-write (refs): remote not-asked, no fetch tried (the origin is away and nothing is said), the clock cache is as it was" || no "status refs --no-write: rc=$RC $(cat "$T/v"; head -c 300 "$T/o"; cat "$T/e")"
mv "$ORIGIN.gone" "$ORIGIN"
# the default is unchanged: without --no-write the call fetches and writes the clock cache
rm -f "$OBS"
call XE a QARGI_MARSHAL_MONO=9000 marshal status --all --no-write --json
[ "$RC" = 0 ] && [ ! -e "$OBS" ] && ok "status --no-write (refs): the clock cache is not even made" || no "status refs --no-write makes the cache: rc=$RC"
call XE a QARGI_MARSHAL_MONO=9000 marshal status --all --json
[ "$RC" = 0 ] && jq -e '.remote == "checked"' "$T/o" >/dev/null && [ -s "$OBS" ] && ok "status (refs) without --no-write: fetches, and the clock cache is written (the default is unchanged)" || no "status refs default: rc=$RC $(head -c 200 "$T/o")"

# ================================================================ (9) a local prepare on a claimed feature records the lead id in its run record (lib/local.sh reads it from the one status shape)
call L marshal claim f5 --as carol --goal "prepared"
mkdir -p "$T/scratch2"
env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=carol "$DA" local prepare --repo "$R" --base feature/f5 --slug pj1 --scratch "$T/scratch2" >"$T/o" 2>"$T/e"; RC=$?
[ "$RC" = 0 ] && [ "$(jq -r 'select(.slug == "pj1") | .lead' "$L0/s/local-runs.jsonl" 2>/dev/null)" = carol ] && ok "local prepare: the run record of a claimed feature holds the lead id" || no "local prepare lead: rc=$RC $(cat "$T/e"; cat "$L0/s/local-runs.jsonl" 2>&1 | head -c 300)"

# the shared records, check: nothing fetched, nothing written under the state's features, the answer says not-asked
cp "$OBS" "$T/obs.before2"; rm -rf "$T/afeatures.before2"; cp -a "$T/m/a/s/features" "$T/afeatures.before2"
mv "$ORIGIN" "$ORIGIN.gone"
call XE a QARGI_MARSHAL_MONO=12000 QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice --no-write --json
[ "$RC" = 0 ] && valid qargi-marshal-check && jq -e '.remote == "not-asked" and .answer == "yours"' "$T/o" >/dev/null && cmp -s "$OBS" "$T/obs.before2" && diff -r "$T/afeatures.before2" "$T/m/a/s/features" >/dev/null \
  && ok "check --no-write (refs): remote not-asked, nothing under the state's features changed" || no "check refs --no-write: rc=$RC $(cat "$T/v"; head -c 300 "$T/o"; cat "$T/e")"
rm -f "$T/m/a/s/audit.log"
call XE a QARGI_REMOTE_TIMEOUT=2 marshal check r1 --as alice --no-write --assume-unreachable-ok --json
[ "$RC" = 0 ] && jq -e '.remote == "not-asked"' "$T/o" >/dev/null && [ ! -e "$T/m/a/s/audit.log" ] && ok "check --no-write --assume-unreachable-ok (refs): no audit line" || no "check refs --no-write --assume: rc=$RC $(cat "$T/e"; cat "$T/m/a/s/audit.log" 2>&1)"
mv "$ORIGIN.gone" "$ORIGIN"
[ "$fail" = 0 ] && echo "all ok" || echo "FAILURES"
exit "$fail"
