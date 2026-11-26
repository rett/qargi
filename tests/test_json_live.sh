#!/usr/bin/env bash
# The live lint of the JSON kinds (lib/kinds): the real output of every pinned verb, on both backends of the marshal, is what its registry file
# and the fixtures of tests/fixtures/json say. The static lint (tests/test_json_registry.py) compares files with files; this one runs the verbs.
#   1. the page docs/reference/json-output.md says what each verb writes, in the words of the registry files;
#   2. the fixed scenario of tests/fixtures/json/scenario.sh (a local project, one with many features and a shared refs one, the clocks held) is run
#      for real, and its output is what the golden files hold, byte for byte once the values of the machine are replaced (a new field in the code
#      fails here until the registry and the golden files follow in the same change), and each output file validates against its registry file
#      and has no field that the registry does not name;
#   3. one world on the local backend and one on the refs backend (with the monotonic clock held): every verb of every pinned kind, with and without
#      NAME and --no-write, prints exactly one valid document with no field the registry does not name; minutes_since_renewal is an integer;
#      --no-write changes nothing; a refusal prints nothing on stdout and one valid qargi-refusal line whose exit is the exit status;
#   4. with the remote of the refs backend unreachable: status exits 0 and says remote unchecked, check exits 3 with the coded line, and check
#      --assume-unreachable-ok exits 0 and says unchecked;
#   5. a verb whose stdout is a closed pipe exits non-zero, with no traceback.
# check --json is called as a user calls it (no QARGI_NO_JSON_WRAP): the command table must leave it alone. A marshal verb refuses inside a run
# directory of qargi, so this runs from the checkout, or from a copy of the tree that is not inside one.
# Run: tests/test_json_live.sh
set -u
cd "$(dirname "$0")/.." || exit 1
OUTER_TMP=${TMPDIR:-}      # the caller's: the scenario pads its scratch directory to a fixed length, so it must run under a short one
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
KINDS=$(ls lib/kinds | sed 's/\.json$//')

# the field of an output that its registry file does not name (drift), one per line; the prefix of a refusal line is taken off
cat > "$T/drift.py" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1] + "/lib")
import jsonkind as J
reg, _ = J.load_registry(J.registry_path(sys.argv[2]))
text = open(sys.argv[3], encoding="utf-8").read()
if reg["stream"] == "stderr":
    text = text.split(" ", 1)[1]
shape = reg["document"]
defs = shape.get("$defs", {})
found = []


def walk(v, node, path):
    while "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[1]]
    if isinstance(v, dict):
        props, extra = node.get("properties"), node.get("additionalProperties")
        for k, x in v.items():
            if props is not None and k in props:
                walk(x, props[k], path + "." + k)
            elif isinstance(extra, dict):
                walk(x, extra, path + "." + k)
            elif props is not None:
                found.append(path + "." + k)
    elif isinstance(v, list) and isinstance(node.get("items"), dict):
        for i, x in enumerate(v):
            walk(x, node["items"], "%s[%d]" % (path, i))


walk(json.loads(text), shape, "$")
print("\n".join(found))
PY

# kind_of FILE: the kind a raw output of the scenario is of, by its name
kind_of() { case $(basename "$1") in status.*) echo qargi-marshal-status;; check.*) echo qargi-marshal-check;; handoff.*) echo qargi-handoff;; refusal.*) echo qargi-refusal;; esac; }
# body_of KIND FILE: the document of a file (the contract line of a refusal without its prefix)
body_of() { if [ "$1" = qargi-refusal ]; then sed 's/^qargi-refusal\/[0-9]* //' "$2"; else cat "$2"; fi; }
# lint KIND FILE LABEL: FILE is one document of KIND, valid against the registry file, with no field the registry does not name; says why when not
lint() {
  local kind=$1 f=$2 d
  [ -s "$f" ] || { echo "$3: no output"; return 1; }
  [ "$(wc -l < "$f")" = 1 ] || [ "$kind" != qargi-refusal ] || { echo "$3: the line is more than one line"; return 1; }
  [ "$(tail -c1 "$f" | od -An -c | tr -d ' ')" = '\n' ] || { echo "$3: the output does not end with a newline"; return 1; }
  body_of "$kind" "$f" | $JK validate "$kind" - 2>"$T/v" || { echo "$3: not valid: $(head -c 400 "$T/v")"; return 1; }
  body_of "$kind" "$f" > "$T/body"
  d=$(python3 -I "$T/drift.py" "$TOOL" "$kind" "$f" 2>&1) || { echo "$3: the drift check failed: $d"; return 1; }
  [ -z "$d" ] || { echo "$3: fields the registry does not name: $(echo "$d" | tr '\n' ' ')"; return 1; }
}

# ================================================================ (1) the page says what each verb writes, in the words of the registry
for k in $KINDS; do
  w=$(jq -r .writes "lib/kinds/$k.json")
  tr -d '`' < docs/reference/json-output.md | grep -qF -e "$w" && ok "docs/reference/json-output.md holds the writes sentence of $k" || no "docs/reference/json-output.md does not hold the writes sentence of $k: $w"
  grep -qF -e "\`$k\`" docs/reference/json-output.md && ok "the page names $k" || no "the page does not name $k"
done

# ================================================================ (2) the scenario: real output, byte for byte the golden files, and valid
# the scratch directory of the scenario is padded to a fixed length by the test it runs in, so TMPDIR must be short enough for that
if [ -n "$OUTER_TMP" ]; then export TMPDIR=$OUTER_TMP; else unset TMPDIR; fi
out=$(python3 tests/test_json_registry.py --regen --check --tool "$TOOL" --keep-raw "$T/raw" 2>&1); rc=$?
export TMPDIR=$T/tmp
[ "$rc" = 0 ] && ok "the scenario's output is what the golden files hold ($(echo "$out" | tail -1))" || no "the scenario differs from the golden files: $(echo "$out" | tail -8)"
n=0
for f in "$T"/raw/*; do
  case $(basename "$f") in _context.json) continue;; esac
  k=$(kind_of "$f"); n=$((n + 1))
  msg=$(lint "$k" "$f" "$(basename "$f")") && ok "scenario $(basename "$f"): one valid $k document, no field the registry does not name" || no "scenario: $msg"
done
[ "$n" = 13 ] && ok "the scenario printed the 13 documents of the four kinds" || no "the scenario printed $n files, not 13"

# ================================================================ (3) the local backend
NOW=1000000
L0=$T/l
mkdir -p "$L0/home" "$L0/c/projects" "$L0/s/features"
R=$L0/app; make_repo "$R"
for n in f1 f2 f3; do git -C "$R" branch "feature/$n" develop; done
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, models:{provider:{local:"claude-code",cloud:"claude-platform"}}, test_command:"true"}' > "$L0/c/projects/app.json"
# L ARGS...: qargi on the local project at the clock $NOW; stdout and stderr in $T/o and $T/e, the exit status kept in RC
L() { env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op "$DA" "$@" >"$T/o" 2>"$T/e"; RC=$?; }
# XE ARGS...: the same on machine a of the refs backend, with the monotonic clock $MONO
XE() { env HOME="$T/m/a/home" QARGI_CONF="$T/m/a/c" QARGI_STATE="$T/m/a/s" QARGI_MARSHAL_NOW="$NOW" QARGI_MARSHAL_MONO="${MONO:-1000}" QARGI_REMOTE_TIMEOUT=2 QARGI_LEAD=op "$DA" "$@" >"$T/o" 2>"$T/e"; RC=$?; }
# refusal CODE EXIT: the last call exited EXIT, wrote nothing to stdout, and has one valid contract line of CODE on stderr whose exit is the exit status
refusal() {
  local line
  [ "$RC" = "$2" ] || { echo "exit $RC, not $2"; return 1; }
  [ ! -s "$T/o" ] || { echo "stdout is not empty"; return 1; }
  [ "$(grep -c '^qargi-refusal/1 ' "$T/e")" = 1 ] || { echo "not one contract line: $(cat "$T/e")"; return 1; }
  grep -m1 '^qargi-refusal/1 ' "$T/e" > "$T/line"
  lint qargi-refusal "$T/line" "the contract line" || return 1
  line=$(sed 's/^qargi-refusal\/1 //' "$T/line")
  [ "$(jq -r '[.code, .exit] | @tsv' <<<"$line")" = "$(printf '%s\t%s' "$1" "$2")" ] || { echo "not code $1 exit $2: $line"; return 1; }
  ! grep -q '^Traceback' "$T/e" || { echo "a traceback"; return 1; }
}
# doc KIND LABEL: the last call exited 0 and its standard output is one valid document of KIND
doc() { [ "$RC" = 0 ] || { echo "$2: exit $RC: $(head -c 300 "$T/e")"; return 1; }; lint "$1" "$T/o" "$2"; }

L marshal claim f1 --as alice --goal "the goal" && [ "$RC" = 0 ] || no "setup: claim f1 ($RC): $(cat "$T/e")"
NOW=$((NOW + 600))
L marshal status --all --json
msg=$(doc qargi-marshal-status "status --all --json") && jq -e '.kind == "qargi-marshal-status" and .backend == "local" and .remote == "none" and (.features | length) == 3' "$T/o" >/dev/null \
  && ok "local: status --all --json is one valid document, three rows, backend local, remote none" || no "local status --all: ${msg:-$(head -c 300 "$T/o")}"
L marshal status f1 --json
msg=$(doc qargi-marshal-status "status f1 --json") && jq -e '(.features | length) == 1 and .features[0].lease_clock == "wall" and (.features[0].minutes_since_renewal | . == 10)' "$T/o" >/dev/null \
  && ok "local: status NAME --json is the same shape with one row; minutes_since_renewal is the integer 10 on the wall clock" || no "local status f1: ${msg:-$(head -c 300 "$T/o")}"
L marshal check f1 --as alice --json
msg=$(doc qargi-marshal-check "check f1 --json") && jq -e '.kind == "qargi-marshal-check" and .answer == "yours" and (has("verb") | not)' "$T/o" >/dev/null \
  && ok "local: check NAME --json is a qargi-marshal-check document (the command table leaves --json alone), answer yours" || no "local check f1: ${msg:-$(head -c 300 "$T/o")}"
L marshal check --json
msg=$(doc qargi-marshal-check "check --json") && jq -e '.answer == null and (.features | length) == 3' "$T/o" >/dev/null && ok "local: check --json (no NAME) has one row for each open feature" || no "local check all: ${msg:-$(head -c 300 "$T/o")}"
L marshal handoff --json
msg=$(doc qargi-handoff "handoff --json") && jq -e '.backend == "local" and .remote == "none" and .backend_fallback == false' "$T/o" >/dev/null \
  && ok "local: handoff --json is one valid document: backend local, remote none, no fallback" || no "local handoff: ${msg:-$(head -c 300 "$T/o")}"
L marshal handoff f1 --json
msg=$(doc qargi-handoff "handoff f1 --json") && ok "local: handoff NAME --json is valid" || no "local handoff f1: $msg"

# --no-write: valid documents, remote not-asked on a backend that has a remote, and nothing in the state changes
cp -a "$L0/s" "$T/s.before"
for a in "status --all --json --no-write" "status f1 --json --no-write" "check f1 --as alice --json --no-write" "check --json --no-write"; do
  # shellcheck disable=SC2086  # the words of the call
  L marshal $a; k=qargi-marshal-status; case $a in check*) k=qargi-marshal-check;; esac
  msg=$(doc $k "$a") && ok "local: $a is one valid document" || no "local $a: $msg"
done
diff -r "$T/s.before" "$L0/s" >/dev/null && ok "local: --no-write changed nothing in the state" || no "local: --no-write changed the state: $(diff -r "$T/s.before" "$L0/s" | head -5)"

# refusals: a feature another live lead holds, and one that does not exist
NOW=$((NOW + 10))
L marshal check f1 --as bob --json
msg=$(refusal marshal-feature-held 1) && ok "local: check --json on a feature another live lead holds is a refusal (marshal-feature-held, exit 1, no document)" || no "local held: $msg"
L marshal check nosuch --json
msg=$(refusal marshal-feature-unknown 1) && ok "local: check --json for a feature that does not exist is marshal-feature-unknown, exit 1" || no "local unknown: $msg"
L marshal status nosuch --json
msg=$(refusal marshal-feature-unknown 1) && ok "local: status --json for a feature that does not exist is marshal-feature-unknown, exit 1" || no "local status unknown: $msg"
L marshal handoff nosuch --json
msg=$(refusal marshal-feature-unknown 1) && ok "local: handoff --json for a feature that does not exist is marshal-feature-unknown, exit 1" || no "local handoff unknown: $msg"

# a closed pipe
for a in "status --all --json" "check --json" "handoff --json"; do
  # shellcheck disable=SC2086
  env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op "$DA" marshal $a >&- 2>"$T/e"; RC=$?
  [ "$RC" != 0 ] && ! grep -q '^Traceback' "$T/e" && ok "local: $a with stdout closed exits non-zero ($RC), no traceback" || no "local $a closed stdout: rc=$RC $(head -c 300 "$T/e")"
done

# ================================================================ (3b) the refs backend, the monotonic clock held
ORIGIN=$T/origin.git
make_origin "$ORIGIN"
make_machine a
for n in r1 r2; do git -C "$T/m/a/app" branch "feature/$n" develop; done
jq '.models = {provider: {local: "claude-code", cloud: "claude-platform"}}' "$T/m/a/c/projects/app.json" > "$T/p.tmp" && cp "$T/p.tmp" "$T/m/a/c/projects/app.json"
WORDS="the shared refs are fine for this project"
XE marshal enable; tk=$(tokof)
XE marshal enable --plan "$tk" --approved "$WORDS"
[ "$RC" = 0 ] && ok "setup: the shared refs are enabled on machine a" || no "setup: enable ($RC): $(cat "$T/e")"
MONO=1000
XE marshal claim r1 --as alice --goal "shared" && [ "$RC" = 0 ] || no "setup: claim r1 ($RC): $(cat "$T/e")"
XE marshal status --all --json
msg=$(doc qargi-marshal-status "status --all --json (the first read)") && jq -e '.features[] | select(.feature == "r1") | .minutes_since_renewal == 0' "$T/o" >/dev/null \
  && ok "refs: the first read on a machine reports 0 minutes" || no "refs first read: ${msg:-$(jq -c '.features[0]' "$T/o")}"
MONO=1600
XE marshal status --all --json
msg=$(doc qargi-marshal-status "status --all --json") && jq -e '.backend == "refs" and .remote == "checked" and (.features[] | select(.feature == "r1") | .lease_clock == "observed-here")' "$T/o" >/dev/null \
  && ok "refs: status --all --json is valid: backend refs, remote checked, lease_clock observed-here" || no "refs status: ${msg:-$(head -c 300 "$T/o")}"
jq -e '.features[] | select(.feature == "r1") | .minutes_since_renewal | . == 10' "$T/o" >/dev/null && ! grep -Eq '"minutes_since_renewal": *-?[0-9]+[.eE]' "$T/o" \
  && ok "refs: with the monotonic clock held, minutes_since_renewal is the integer 10, not a float" || no "refs minutes_since_renewal: $(jq -c '.features[] | select(.feature == "r1")' "$T/o" | head -c 400)"
XE marshal status r1 --json
msg=$(doc qargi-marshal-status "status r1 --json") && ok "refs: status NAME --json is valid" || no "refs status r1: $msg"
XE marshal check r1 --as alice --json
msg=$(doc qargi-marshal-check "check r1 --json") && jq -e '.backend == "refs" and .remote == "checked" and .answer == "yours"' "$T/o" >/dev/null && ok "refs: check NAME --json is valid: remote checked, answer yours" || no "refs check r1: ${msg:-$(head -c 300 "$T/o")}"
XE marshal check --json
msg=$(doc qargi-marshal-check "check --json") && jq -e '[.features[] | select(.lead != null) | .minutes_since_renewal | type] | all(. == "number")' "$T/o" >/dev/null && ok "refs: check --json (no NAME) is valid, a lease age in every row" || no "refs check all: ${msg:-$(head -c 300 "$T/o")}"
XE marshal handoff --json
msg=$(doc qargi-handoff "handoff --json") && jq -e '.backend == "refs" and .remote == "not-asked" and .backend_fallback == false' "$T/o" >/dev/null \
  && ok "refs: handoff --json is valid: backend refs, remote not-asked (it never fetches), no fallback" || no "refs handoff: ${msg:-$(head -c 300 "$T/o")}"
cp -a "$T/m/a/s" "$T/a.s.before"
for a in "status --all --json --no-write" "check r1 --as alice --json --no-write"; do
  # shellcheck disable=SC2086
  XE marshal $a; k=qargi-marshal-status; case $a in check*) k=qargi-marshal-check;; esac
  msg=$(doc $k "$a") && jq -e '.remote == "not-asked"' "$T/o" >/dev/null && ok "refs: $a is valid and says remote not-asked" || no "refs $a: ${msg:-$(head -c 300 "$T/o")}"
done
diff -r "$T/a.s.before" "$T/m/a/s" >/dev/null && ok "refs: --no-write changed nothing in the state of the machine" || no "refs: --no-write changed the state: $(diff -r "$T/a.s.before" "$T/m/a/s" | head -5)"
XE marshal check r1 --as bob --json
msg=$(refusal marshal-feature-held 1) && ok "refs: check --json on a feature another live lead holds is marshal-feature-held, exit 1, no document" || no "refs held: $msg"
for a in "status --all --json" "check --json" "handoff --json"; do
  # shellcheck disable=SC2086
  env HOME="$T/m/a/home" QARGI_CONF="$T/m/a/c" QARGI_STATE="$T/m/a/s" QARGI_MARSHAL_NOW="$NOW" QARGI_MARSHAL_MONO=1600 QARGI_LEAD=op "$DA" marshal $a >&- 2>"$T/e"; RC=$?
  [ "$RC" != 0 ] && ! grep -q '^Traceback' "$T/e" && ok "refs: $a with stdout closed exits non-zero ($RC), no traceback" || no "refs $a closed stdout: rc=$RC $(head -c 300 "$T/e")"
done

# ================================================================ (4) the remote of the shared records cannot be reached
mv "$ORIGIN" "$ORIGIN.gone"
XE marshal status r1 --json
msg=$(doc qargi-marshal-status "status r1 --json") && jq -e '.remote == "unchecked" and .backend == "refs"' "$T/o" >/dev/null \
  && ok "unreachable remote: status --json exits 0 from the cache and says remote unchecked" || no "unreachable status: rc=$RC ${msg:-$(head -c 300 "$T/o")}"
XE marshal check r1 --as alice --json
msg=$(refusal marshal-remote-unreachable 3) && ok "unreachable remote: check --json exits 3 with the coded line (marshal-remote-unreachable) and no document" || no "unreachable check: $msg"
XE marshal check --json
msg=$(refusal marshal-remote-unreachable 3) && ok "unreachable remote: check --json with no NAME is the same" || no "unreachable check all: $msg"
XE marshal check r1 --as alice --json --assume-unreachable-ok
msg=$(doc qargi-marshal-check "check --assume-unreachable-ok") && jq -e '.remote == "unchecked" and .answer == "yours"' "$T/o" >/dev/null \
  && ok "unreachable remote: check --assume-unreachable-ok exits 0 from the cache and says remote unchecked" || no "unreachable check override: rc=$RC ${msg:-$(head -c 300 "$T/o")}"
XE marshal handoff --json
msg=$(doc qargi-handoff "handoff --json") && ok "unreachable remote: handoff --json (it never fetches) is valid" || no "unreachable handoff: $msg"
mv "$ORIGIN.gone" "$ORIGIN"

[ "$fail" = 0 ] && echo "all ok" || { echo "FAILED"; exit 1; }
