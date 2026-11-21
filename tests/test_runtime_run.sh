#!/usr/bin/env bash
# A run on one of several runtimes (the third task of the runtime-per-profile design): `qargi local prepare` resolves the runtime of a run (the task's
# --runtime, the runtime a profile names, the project's own) before anything else, asks the read-only barrier of THAT runtime, binds the run to it, and
# records it in the lead's registry; `qargi local run` starts the run on the runtime it was prepared for or refuses (runtime-drift); `local list` and
# `review check` show it; verify, review, apply, close and clean never ask for a runtime. A project without extra runtimes (models.extra_runtimes.local
# empty) sees nothing new: its prepare output, registry line and run list are the ones recorded in tests/fixtures/runtime-no-extras before the change.
# Hermetic and offline: a copy of the tool holds the fake command runtimes (tests/fakeprov.sh), the scratch directories are under the test's own
# directory (TMPDIR on disk: the shipped codex definition hides /dev, so a test under /dev/shm would refuse its own runs).
# Run: tests/test_runtime_run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
umask 077
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_AUTHOR_DATE GIT_COMMITTER_DATE
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
unset QARGI_PROJECT QARGI_LEAD_RUNTIME
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp" "$T/scr" "$HOME/.codex-members"
echo '{}' > "$HOME/.codex-members/auth.json"   # the members' sign-in of the shipped codex: a file of the test's own home
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
NX=$SRC/tests/fixtures/runtime-no-extras
LC="git -c user.name=t -c user.email=t@example.net"
# the shipped codex definition hides /dev, and a TMPDIR under /dev/shm would refuse every run of a codex-derived runtime: the copy of the tool
# hides HID, a path no run lies under, in its place (the suite may run under /dev/shm; the hidden-path refusal is tested with a prefix of its own)
HID=$T/hidden-by-the-sandbox
jq --arg h "$HID" '.dispatch.hidden_paths.prefixes = [$h]' "$SRC/lib/providers/codex.json" > "$TOOL/lib/providers/codex.json"
ok() { echo "ok $1"; }
no() { echo "FAIL $1"; fail=1; }

# --- a project without extras: what prepare printed, what the registry recorded and what the list showed are on record (tests/fixtures/
# runtime-no-extras, recorded from the head before the change). Paths, run names, times and commit ids are masked; everything else must not move.
mkrepo() { # DIR: a repository with develop and master at one commit
  git init -q -b master "$1" && $LC -C "$1" commit -q --allow-empty -m one && git -C "$1" branch develop
}
mask() { sed -e "s#$T#T#g" -e 's/qargi\.[A-Za-z0-9]\{6\}/qargi.XXXXXX/g' -e 's/qargi-run\.[A-Za-z0-9]\{6\}/qargi-run.XXXXXX/g' -e 's/[0-9a-f]\{40\}/SHA/g'; }
nx_project() { # NAME FIXTURE: the stored answers of a fixture project, with a repository of its own
  mkrepo "$T/repo-$1"
  jq --arg p "$T/repo-$1" --arg n "$1" '.repo.path = $p | .project = $n' "$NX/$2.json" > "$T/c/projects/$1.json"
}
nx_prep() { # PROJECT ARGS...: a prepare in the project's repository, its output (standard error too) masked; the run is left in RUN
  local p=$1; shift
  PREP=$("$DA" local prepare --repo "$T/repo-$p" --base develop --scratch "$T/scr" "$@" 2>&1); PREP_RC=$?
  RUN=$(sed -n 's/^RUN=//p' <<<"$PREP")
  echo "--- prepare $p $*"; mask <<<"$PREP"; echo "exit $PREP_RC"
}
nx_registry() { # RUN: the registry line of the run, with what changes from one run to the next masked
  jq -S --arg r "$1" 'select(.run == $r) | .run = "RUN" | .tmpdir = "TMP" | del(.started) | if has("repo") then .repo = "REPO" else . end' "$QARGI_STATE/local-runs.jsonl"
}
nx_scene() { # PROJECT: two prepares (a build with a profile, a review), their registry lines and the run list
  nx_prep "$1" --slug nxa --profile worker-fast; nx_registry "$RUN"
  nx_prep "$1" --slug nxb --role review; nx_registry "$RUN"
  echo "--- local list --json"
  "$DA" local list --json | jq -S . | mask | sed 's/[0-9][0-9]*[mhd] /AGE /g'
}
nx_project nxsession project
nx_project nxcommand project-command
"$DA" agent add worker --roles build,write,test --project nxsession >/dev/null 2>&1
"$DA" agent add reviewer --roles review --project nxsession >/dev/null 2>&1
if [ -n "${NX_RECORD:-}" ]; then    # the head before the change is run once with NX_RECORD=DIR, and the fixture is what it printed
  nx_scene nxsession > "$NX_RECORD/prepare-session.golden" 2>&1
  nx_scene nxcommand > "$NX_RECORD/prepare-command.golden" 2>&1
  exit 0
fi
nxbad=''
for pair in session:nxsession command:nxcommand; do
  out=$(nx_scene "${pair##*:}" 2>&1)
  [ "$out" = "$(cat "$NX/prepare-${pair%%:*}.golden")" ] \
    || { nxbad=1; no "no extras: prepare, the registry line and the run list of the ${pair%%:*} fixture project changed:"; diff <(echo "$out") "$NX/prepare-${pair%%:*}.golden" | head -20; }
done
[ -n "$nxbad" ] || ok no-extras-identical

# --- the runtimes: fakes of the shipped codex definition (a command runtime started by qargi local run), each hiding a path no run lies under
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
NOHIDE='.dispatch.hidden_paths.prefixes = ["'"$HID"'"]'
BARRIER() { printf '.capabilities.read_only_barrier |= (.value = "%s" | .verified_on = "2026-11-11")' "$1"; }
VERIFIED='.capabilities.per_dispatch_model_override.verified_on = "2026-11-02"'
export PATH=$TOOL/stubs:$PATH          # a runtime's command is found by name on PATH
mkfake() { # NAME FILTER: a fake command runtime whose command is its stub by name, its sign-in a file of the test's home
  fake_command_runtime "$SRC" "$TOOL" "$1" ".dispatch.argv[0] = \"$1\" | $NOHIDE | ${2:-.}"
  mkdir -p "$HOME/.$1-members"; echo '{}' > "$HOME/.$1-members/auth.json"
}
mkfake fakecx                           # partial barrier, the model override unverified (the shipped claims)
mkfake fakever "$VERIFIED"              # the same, its model override verified
mkfake fakeno "$(BARRIER no)"           # no read-only barrier
mkfake fakeown "$(BARRIER no)"          # a project's own runtime whose missing barrier the project accepted
mkfake fakehid '.dispatch.hidden_paths.prefixes = ["'"$T"'/hid"]'
mkdir -p "$T/hid"
mkproj() { # NAME PROVIDER-JSON EXTRAS-JSON PROFILES-JSON [ACCEPT]: stored answers with a repository of their own (and the members of an in-session own runtime)
  local repo=$T/repo-$1
  git init -q -b main "$repo" && $LC -C "$repo" commit -q --allow-empty -m one
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" --argjson ex "${3:-null}" --argjson pr "${4:-null}" --argjson acc "${5:-null}" \
    '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
      roles:{build:{base:"main",push:{mode:"none"}},review:{base:"main",push:{mode:"none"}}}, profiles:($pr // {}),
      models:({provider:$prov} + (if $ex == null then {} else {extra_runtimes:{local:$ex}} end) + (if $acc == null then {} else {accept_no_barrier:{local:$acc}} end)),
      memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
  if [ "$(jq -r .local <<<"$2")" = claude-code ]; then
    "$DA" agent add worker --roles build,write,test --project "$1" >/dev/null 2>&1; "$DA" agent add reviewer --roles review --project "$1" >/dev/null 2>&1
  fi
}
CC='{"local":"claude-code","cloud":"claude-platform"}'
ACC='{"by":"me","at":"2026-11-11T12:00:00Z","reason":"the owner said so"}'
PROFILES='{"cx-build":{"base":"worker","tier":"balanced","effort":"high","runtime":"fakecx"},"cx-review":{"base":"reviewer","tier":"deep","runtime":"fakecx"},
  "cc-fast":{"base":"worker","tier":"fast","effort":"low"},"cc-own":{"base":"worker","tier":"fast","runtime":"claude-code"}}'
mkproj two "$CC" '["fakecx","fakever","fakeno"]' "$PROFILES"
mkproj cmd '{"local":"fakeown"}' '["fakeno","fakecx"]' null "$ACC"
prep() { # PROJECT ARGS...: local prepare in the project's repository, standard error with standard output: PREP, PREP_RC and RUN
  local p=$1; shift
  PREP=$("$DA" local prepare --repo "$T/repo-$p" --base main --scratch "${SCRATCH:-$T/scr}" "$@" 2>&1); PREP_RC=$?
  RUN=$(sed -n 's/^RUN=//p' <<<"$PREP")
}
line() { sed -n "s/^$1=//p" <<<"$PREP"; }          # the value of a KEY= line of the last prepare
regline() { jq -c --arg r "$1" 'select(.run == $r)' "$QARGI_STATE/local-runs.jsonl"; }
refusal_code() { sed -n 's/^qargi-refusal\/1 .*"code":"\([a-z-]*\)".*/\1/p' <<<"$1"; }
made() { { ls "$T/scr"; ls -d "$T"/qargi-run.* 2>/dev/null; } | wc -l; }   # what a prepare leaves: run directories and temporary directories

# --- prepare resolves the runtime of the run: --runtime, else the profile's, else the project's own; a project with extras names it
prep two --slug a1 --profile cx-build
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && [ "$(line MEMBER)" = worker ] && [ "$(line MODEL)" = gpt-6.1-terra ] && [ "$(line EFFORT)" = high ] \
  && ! grep -q '^RUNTIME_OVERRIDE=' <<<"$PREP" && grep -qx 'MEMBER_SKILLS=none (not delivered to an extra runtime)' <<<"$PREP"; } && ok prepare-profile-runtime || no "profile runtime: rc=$PREP_RC $PREP"
jq -e '.runtime == "fakecx" and .model_confirmed == false and .model == "gpt-6.1-terra" and .command_request == 1 and .profile == "cx-build"' <<<"$(regline "$RUN")" >/dev/null \
  && ok registry-extra-runtime || no "registry line: $(regline "$RUN")"
jq -e '.runtime == "fakecx"' "$RUN/request.json" >/dev/null && ok request-mirror-names-runtime || no "request.json: $(cat "$RUN/request.json")"
prep two --slug a2 --profile cx-build --runtime fakever
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakever ] && [ "$(line MODEL)" = gpt-6.1-terra ] \
  && [ "$(line RUNTIME_OVERRIDE)" = "profile cx-build names fakecx, resolved in fakever: gpt-6.1-terra high" ]; } && ok override-profile-runtime || no "override of a profile's runtime: rc=$PREP_RC $PREP"
jq -e '.runtime == "fakever" and .model_confirmed == true' <<<"$(regline "$RUN")" >/dev/null && ok registry-override-verified || no "registry line, verified override: $(regline "$RUN")"
prep two --slug a3 --profile cc-fast --runtime fakecx
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && [ "$(line RUNTIME_OVERRIDE)" = "profile cc-fast names no runtime (claude-code), resolved in fakecx: gpt-6-luna low" ]; } \
  && ok override-no-profile-runtime || no "override of a profile with no runtime: rc=$PREP_RC $PREP"
prep two --slug a3b --runtime fakecx
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME_OVERRIDE)" = "profile build names no runtime (claude-code), resolved in fakecx: gpt-6.1-terra high" ] && [ "$(line PROFILE)" = build ]; } \
  && ok override-no-profile-given || no "override with no profile given: rc=$PREP_RC $PREP"
prep two --slug a4 --profile cx-build --runtime fakecx
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && ! grep -q RUNTIME_OVERRIDE <<<"$PREP"; } && ok override-silent-same || no "an option equal to the profile's runtime: rc=$PREP_RC $PREP"
prep two --slug a5 --profile cc-fast --runtime claude-code
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = claude-code ] && ! grep -q RUNTIME_OVERRIDE <<<"$PREP" && [ "$(line MODEL)" = haiku ]; } && ok override-silent-primary || no "the project's own as an option: rc=$PREP_RC $PREP"
prep two --slug a6 --profile cx-build --runtime claude-code
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = claude-code ] && [ "$(line RUNTIME_OVERRIDE)" = "profile cx-build names fakecx, resolved in claude-code: sonnet high" ]; } \
  && ok override-to-primary || no "an option naming the project's own against a profile of an extra: rc=$PREP_RC $PREP"
before=$(made)
prep two --slug a7 --runtime nosuch
{ [ "$PREP_RC" = 1 ] && [ "$(refusal_code "$PREP")" = runtime-not-enabled ] && [ "$(made)" = "$before" ]; } && ok prepare-runtime-not-enabled || no "a runtime not enabled: rc=$PREP_RC $PREP"

# --- the read-only barrier is the barrier of the runtime the run is prepared for, asked after that runtime is known (F5). The project's own runtime has no
# barrier and the project accepted that; the extra one has none either. The acceptance is for the own runtime and does not let the extra one start.
before=$(made)
prep cmd --slug f1 --role review --runtime fakeno
{ [ "$PREP_RC" = 1 ] && [ "$(refusal_code "$PREP")" = runtime-barrier-missing ] && grep -q 'name=fakeno' <<<"$PREP" && [ "$(made)" = "$before" ]; } \
  && ok barrier-order || no "an accepted own runtime must not carry an extra one without a barrier: rc=$PREP_RC made=$(made)/$before $PREP"
prep cmd --slug f2 --role review
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakeown ] && [ "$(line ROLE)" = review ]; } && ok barrier-own-accepted || no "the own runtime, accepted: rc=$PREP_RC $PREP"
prep cmd --slug f3 --role review --runtime fakecx
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && grep -q 'qargi: note: fakecx has only a partial read-only barrier on local' <<<"$PREP"; } \
  && ok barrier-partial-extra || no "an extra runtime with a partial barrier: rc=$PREP_RC $PREP"
prep two --slug f4 --role review --runtime fakeno
{ [ "$PREP_RC" = 1 ] && [ "$(refusal_code "$PREP")" = runtime-barrier-missing ]; } && ok barrier-missing-extra || no "an extra runtime with no barrier: rc=$PREP_RC $PREP"

# --- the sandbox of the runtime the run is prepared for decides what the member sees: a scratch under a path that runtime hides is refused before RUN exists,
# and the project's own runtime (in session: nothing is hidden) takes the same scratch
mkproj hidp "$CC" '["fakehid"]' null
before=$(made)
SCRATCH=$T/hid prep hidp --slug h1 --runtime fakehid
{ [ "$PREP_RC" = 2 ] && grep -q 'the member of this write run of fakehid would not see what it works with' <<<"$PREP" && grep -q "CONTRACT $T/hid/qargi.XXXXXX/contract lies under $T/hid" <<<"$PREP" \
  && grep -q 'Nothing was started: prepare the run again with --scratch on another filesystem' <<<"$PREP" && [ -z "$(ls -A "$T/hid")" ] && [ "$(made)" = "$before" ]; } \
  && ok hidden-path-extra || no "a scratch under a path the extra runtime hides: rc=$PREP_RC $PREP"
SCRATCH=$T/hid prep hidp --slug h2
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = claude-code ] && [ -d "$RUN/clone" ]; } && ok hidden-path-own-runtime-shows-all || no "the own runtime in the same place: rc=$PREP_RC $PREP"

# --- managed member skills are delivered to the project's own runtime only: a project that opted in, a run on an extra runtime freezes none and says so
mkproj skl '{"local":"fakeown"}' '["fakecx"]' null "$ACC"
jq '.packs = {member_skills: true}' "$T/c/projects/skl.json" > "$T/skl.json" && mv "$T/skl.json" "$T/c/projects/skl.json"
frozen() { # RUN: does the lifecycle record of the run hold a snapshot of managed skills?
  python3 -I -c 'import sys
sys.path.insert(0, sys.argv[1] + "/lib")
import attempts as A
print("skills" in A.Store(sys.argv[2]).show()["prepared"])' "$TOOL" "$1"
}
prep skl --slug s1 --runtime fakecx
{ [ "$PREP_RC" = 0 ] && grep -qx 'MEMBER_SKILLS=none (not delivered to an extra runtime)' <<<"$PREP" && [ "$(frozen "$RUN")" = False ]; } \
  && ok member-skills-extra-none || no "member skills on an extra runtime: rc=$PREP_RC frozen=$(frozen "$RUN") $PREP"
prep skl --slug s2
{ [ "$PREP_RC" = 0 ] && ! grep -q '^MEMBER_SKILLS=' <<<"$PREP" && [ "$(frozen "$RUN")" = True ]; } \
  && ok member-skills-own-frozen || no "member skills on the own runtime: rc=$PREP_RC frozen=$(frozen "$RUN") $PREP"

# --- the registry line of the project's own runtime, in session or as a command, names it too (a project with extras), and the agreement check of the
# lifecycle compares the runtime of the line with the request's where a request exists
prep two --slug r1
jq -e '.runtime == "claude-code" and .model_confirmed == true and (has("command_request") | not) and (has("model") | not)' <<<"$(regline "$RUN")" >/dev/null \
  && ok registry-insession-line || no "the line of an in-session run of the own runtime: $(regline "$RUN")"
READY() { # RUN: the lifecycle record read as the verbs read it (the agreement of the registry line with the prepared request is checked there); exit 1 and the reason when it refuses
  python3 -I -c 'import sys
sys.path.insert(0, sys.argv[1] + "/lib")
import attempts as A
try:
    A.Store(sys.argv[2]).show()
except (A.Refuse, A.Legacy) as e:
    print(e)
    sys.exit(1)' "$TOOL" "$1" 2>&1
}
READY "$RUN" >/dev/null && ok insession-line-no-request || no "an in-session line with a runtime and no request: $(READY "$RUN")"
prep cmd --slug r2
jq -e '.runtime == "fakeown" and .model_confirmed == false and .command_request == 1' <<<"$(regline "$RUN")" >/dev/null && ok registry-command-own-line || no "the line of a command run of the own runtime: $(regline "$RUN")"
CMDOWN=$RUN
READY "$CMDOWN" >/dev/null && ok agreement-holds || no "the agreement of a line and its request: $(READY "$CMDOWN")"
setline() { # RUN JQ-FILTER: the registry line of RUN rewritten by the filter, by hand (what a damaged or edited line looks like)
  local f=$QARGI_STATE/local-runs.jsonl
  jq -c --arg r "$1" "if .run == \$r then ($2) else . end" "$f" > "$f.new" && mv "$f.new" "$f"
}

exit $fail
