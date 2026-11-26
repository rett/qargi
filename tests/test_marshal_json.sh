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

[ "$fail" = 0 ] && echo "all ok" || echo "FAILURES"
exit "$fail"
