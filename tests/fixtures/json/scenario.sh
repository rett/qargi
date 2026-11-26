#!/usr/bin/env bash
# The one fixed scenario the golden files of tests/fixtures/json/ come from: a scratch project on the local backend, one on the shared refs
# backend and one with many features, the clocks held, then every verb of the four pinned kinds run for real. It prints nothing but the raw
# outputs, one file each, in the directory given as its only argument, and the scratch directory, host and user it ran with in `_context.json`:
# `python3 tests/test_json_registry.py --regen` runs it, replaces what depends on the machine (paths, host, user) and writes the golden
# files. A consumer of the fixtures does not need this file.
# Run: bash tests/fixtures/json/scenario.sh OUTDIR   (from anywhere; the checkout it lives in is the qargi under test)
set -u
OUT=${1:?usage: scenario.sh OUTDIR}
cd "$(dirname "$0")/../../.." || exit 1
# shellcheck source=../../hermetic.sh
. tests/hermetic.sh
# shellcheck source=../../fixtures.sh
. tests/fixtures.sh
T=$(mktemp -d); DA=$PWD/bin/qargi; mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
trap 'kill_bg; rm -rf "$T" "$HERMETIC"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export GIT_COMMITTER_DATE="2026-01-01T00:00:00Z" GIT_AUTHOR_DATE="2026-01-01T00:00:00Z"
export QARGI_PROJECT=app TMPDIR=$T/tmp; mkdir -p "$TMPDIR"
NOW=1000000            # the wall clock of the marshal (QARGI_MARSHAL_NOW), held
die() { echo "scenario: $*" >&2; exit 1; }
jq -n --arg t "$T" --arg h "$(hostname)" --arg u "$(id -un)" '{scratch: $t, host: $h, user: $u}' > "$OUT/_context.json"
# keep NAME CMD...: the stdout of CMD in OUT/NAME, which must exit 0
keep() { local n=$1; shift; "$@" >"$OUT/$n" 2>"$T/err" || die "$n: exit $? ($(head -c 300 "$T/err"))"; }
# refusal NAME CMD...: CMD must exit non-zero with nothing on stdout; the contract line of its stderr is kept in OUT/NAME
refusal() { local n=$1; shift; "$@" >"$T/out" 2>"$T/err" && die "$n: exit 0"; grep -m1 '^qargi-refusal/1 ' "$T/err" >"$OUT/$n" || die "$n: no contract line"; }
# project_answers HOME CONF STATE REPO: the answers of a project "app" for the repository, as `project template` makes them, with a test command and gates
project_answers() {
  env HOME="$1" QARGI_CONF="$2" QARGI_STATE="$3" "$DA" project template app \
    | jq --arg p "$4" '.repo.url = "https://github.com/acme/app" | .repo.path = $p | .methodology = "gitflow" | .test_command = "make test"
      | .models = {provider: {local: "claude-code", cloud: "claude-platform"}}
      | .gates = [{name: "unit", command: "make test", tier: "feature"}, {name: "docs", command: "make docs", tier: "release"}]' || die "project template"
}

# ================================================================ the local backend
L0=$T/l
mkdir -p "$L0/home" "$L0/c/projects" "$L0/s/features"
R=$L0/app; make_repo "$R"
for n in f1 f2 f3; do git -C "$R" branch "feature/$n" develop; done
# f1 has a work tree, a merged and an unmerged agent branch; f3 changes the file f1 changes (the overlap); f2 has a commit and nothing else
git -C "$R" worktree add -q "$L0/wt-f1" feature/f1
echo one > "$L0/wt-f1/shared.txt" && echo f1 > "$L0/wt-f1/f1.txt" && git -C "$L0/wt-f1" add -A && git -C "$L0/wt-f1" commit -q -m "f1: first change"
git -C "$R" branch agent/m1 feature/f1
git -C "$R" branch agent/u1 feature/f1
git -C "$R" worktree add -q "$L0/wt-u1" agent/u1
echo u1 > "$L0/wt-u1/u1.txt" && git -C "$L0/wt-u1" add -A && git -C "$L0/wt-u1" commit -q -m "u1: unmerged agent work"
git -C "$R" worktree add -q -b agent/x1 "$L0/wt-x1" develop
echo x1 > "$L0/wt-x1/x1.txt" && git -C "$L0/wt-x1" add -A && git -C "$L0/wt-x1" commit -q -m "x1: work for a feature that is not open" && git -C "$R" worktree remove --force "$L0/wt-x1"
git -C "$R" worktree add -q --detach "$L0/wt-det" develop
git -C "$R" worktree add -q "$L0/wt-f3" feature/f3
echo three > "$L0/wt-f3/shared.txt" && git -C "$L0/wt-f3" add -A && git -C "$L0/wt-f3" commit -q -m "f3: the same file" && git -C "$R" worktree remove --force "$L0/wt-f3"
git -C "$R" worktree add -q "$L0/wt-f2" feature/f2
echo f2 > "$L0/wt-f2/f2.txt" && git -C "$L0/wt-f2" add -A && git -C "$L0/wt-f2" commit -q -m "f2: a change" && git -C "$R" worktree remove --force "$L0/wt-f2"
git -C "$R" checkout -q -b parked
mkdir -p "$L0/mem/project/shared" && echo "# index" > "$L0/mem/project/shared/INDEX.md" && echo "# rules" > "$R/AGENTS.md"
project_answers "$L0/home" "$L0/c" "$L0/s" "$R" \
  | jq --arg m "$L0/mem/project" '.methodology_accepted = [{gap: "file: CONTRIBUTING.md", reason: "the contributing rules live in the wiki", date: "2026-01-01"}]
    | .memory = {memory_store: "memstore_0000000000000000000000", tiers: {project: {path: $m}}}' > "$L0/c/projects/app.json"
# L ARGS...: qargi on the local project, run from the work tree of f1 (the `cwd` of a handoff), at the clock $NOW
L() { (cd "$L0/wt-f1" && env HOME="$L0/home" QARGI_CONF="$L0/c" QARGI_STATE="$L0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op QARGI_NO_JSON_WRAP=1 "$DA" "$@"); }

L marshal claim f1 --as alice --goal "the first goal" >/dev/null || die "claim f1"
L marshal set f1 --as alice --plan "step one, step two" --note "a note" >/dev/null || die "set f1"
# f2 changes hands to the restarted session of its lead; f3 is finished (its branch stays)
L marshal claim f2 --as dora --goal "the second goal" >/dev/null || die "claim f2"
L marshal claim f3 --as carol --goal "$(head -c 2100 /dev/zero | tr '\0' g)" >/dev/null || die "claim f3"
L marshal finish f3 --as carol >/dev/null || die "finish f3"
# the lead's registry of runs: three runs against feature/f1 (one directory exists) and one against a feature that is not open
mkdir -p "$T/rundir"
printf '%s\n' '{"run":"'"$T"'/rundir","slug":"t1","ability":"build","base":"feature/f1","started":"2026-01-01T00:00:00Z"}' \
  '{"run":"'"$T"'/gone","slug":"t2","ability":"review","base":"feature/f1","started":"2026-01-02T00:00:00Z"}' \
  '{"run":"'"$T"'/gone2","slug":"u1","ability":"build","base":"feature/f1","started":"2026-01-03T00:00:00Z"}' \
  '{"run":"'"$T"'/gone3","slug":"x1","ability":"build","base":"feature/none","started":"2026-01-04T00:00:00Z"}' > "$L0/s/local-runs.jsonl"
git -C "$R" merge -q --no-ff -m "merge agent/m1" agent/m1 2>/dev/null
tipf1=$(git -C "$R" rev-parse feature/f1)
mkdir -p "$L0/s/releases" "$L0/s/env"
jq -n --arg sha "$tipf1" '{sha: $sha, result: "pass", at: "2026-01-01T00:00:00Z", command: "gates: unit=make test", environment: {id: ""}}' > "$L0/s/releases/app-feature_f1.json"
cat > "$L0/s/env/app.json" <<'ENV'
{"check": {"verdict": "ENV OK", "exit": 0, "missing": 0, "expected": 1, "time": "2026-01-01T00:00:00Z", "head": "0000000000000000000000000000000000000000", "doctor_command": "make doctor", "builtin_minimum": false},
 "apply": {"exit": 0, "time": "2026-01-01T00:00:00Z", "command": "make bootstrap", "head": "0000000000000000000000000000000000000000", "allow_root": false}}
ENV

NOW=$((NOW + 20))
refusal refusal.held L marshal check f1 --as bob
keep check.local-yours.json L marshal check f1 --as alice --json
# a lease lapses after 15 minutes: the restarted session of dora continues f2 as its successor, then one and a half hours on every lease is stale
NOW=$((NOW + 1000))
L marshal claim f2 --as dora-2 --as-successor-of dora >/dev/null || die "successor on f2"
NOW=$((NOW + 5400))
keep status.local.json L marshal status --all --json
keep status.local-name.json L marshal status f1 --json
keep check.local.json L marshal check --json
keep check.local-name.json L marshal check f1 --as bob --json
keep check.local-successor.json L marshal check f2 --as bob --json
keep handoff.local.json L marshal handoff --as alice --json

# ================================================================ a project with more features than a handoff holds
B0=$T/b
mkdir -p "$B0/home" "$B0/c/projects" "$B0/s/features"
BR=$B0/app; make_repo "$BR"
for i in $(seq 1 120); do git -C "$BR" branch "feature/a-long-feature-name-for-the-size-limit-$(printf %03d "$i")" develop; done
project_answers "$B0/home" "$B0/c" "$B0/s" "$BR" \
  | jq '.methodology_accepted = [range(60) | {gap: ("file: DOC-" + tostring + ".md"), reason: ("x" * 480), date: "2026-01-01"}]' > "$B0/c/projects/app.json"
B() { env HOME="$B0/home" QARGI_CONF="$B0/c" QARGI_STATE="$B0/s" QARGI_MARSHAL_NOW="$NOW" QARGI_LEAD=op QARGI_NO_JSON_WRAP=1 "$DA" "$@"; }
keep handoff.local-truncated.json B marshal handoff --json

# ================================================================ the shared refs backend, integrity advisory (an unkeyed machine: its records are unsigned)
ORIGIN=$T/origin.git
make_origin "$ORIGIN"
make_machine a
for n in r1 r2; do git -C "$T/m/a/app" branch "feature/$n" develop; done
XE() { env HOME="$T/m/a/home" QARGI_CONF="$T/m/a/c" QARGI_STATE="$T/m/a/s" QARGI_MARSHAL_NOW="$NOW" QARGI_MARSHAL_MONO="${MONO:-1000}" QARGI_LEAD=op QARGI_NO_JSON_WRAP=1 "$@"; }
WORDS="the shared refs are fine for this project"
tk=$(XE "$DA" marshal enable | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
XE "$DA" marshal enable --plan "$tk" --approved "$WORDS" >/dev/null || die "enable the shared refs"
XE "$DA" marshal claim r1 --as alice --goal "shared" >/dev/null || die "claim r1"
jq '.integrity = "advisory"' "$T/m/a/s/marshal/app.enabled" > "$T/en.tmp" && cp "$T/en.tmp" "$T/m/a/s/marshal/app.enabled"
jq '.models = {provider: {local: "claude-code", cloud: "claude-platform"}}' "$T/m/a/c/projects/app.json" > "$T/p.tmp" && cp "$T/p.tmp" "$T/m/a/c/projects/app.json"
XE "$DA" marshal status --all --json >/dev/null || die "the first read on the machine"
MONO=1600
export MONO
keep status.refs.json XE "$DA" marshal status --all --json
keep check.refs-name.json XE "$DA" marshal check r1 --as alice --json
keep check.refs.json XE "$DA" marshal check --json
keep handoff.refs.json XE "$DA" marshal handoff --json
echo "scenario done"
