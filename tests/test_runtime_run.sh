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
mkfake fakedis
mkfake fakechg
mkfake fakeuse
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
mkproj two "$CC" '["fakecx","fakever","fakeno","fakedis","fakechg","fakeuse"]' "$PROFILES"
mkproj cmd '{"local":"fakeown"}' '["fakeno","fakecx"]' null "$ACC"
prep() { # PROJECT ARGS...: local prepare in the project's repository, standard error with standard output: PREP, PREP_RC and RUN
  local p=$1; shift
  PREP=$("$DA" local prepare --repo "$T/repo-$p" --base main --scratch "${SCRATCH:-$T/scr}" "$@" 2>&1); PREP_RC=$?
  RUN=$(sed -n 's/^RUN=//p' <<<"$PREP")
}
line() { sed -n "s/^$1=//p" <<<"$PREP" | head -1; }          # the value of a KEY= line of the last prepare
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

# the profile a role asks for is the one qargi agent for resolves: the profile named like the role, the shipped ones (write, test) included, else build or review. A
# project whose build profile names an extra runtime says nothing of it for the roles write and test, which take the shipped profiles of their own name
mkproj wt "$CC" '["fakecx"]' '{"build":{"runtime":"fakecx"}}'
prep wt --slug w0 --role write
{ [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = claude-code ] && [ "$(line PROFILE)" = write ] && ! grep -q RUNTIME_OVERRIDE <<<"$PREP"; } \
  && ok role-write-own-runtime || no "the write role, no option: rc=$PREP_RC $PREP"
for r in write test; do
  prep wt --slug "${r}x" --role "$r" --runtime fakecx
  { [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && [ "$(line PROFILE)" = "$r" ] \
    && [ "$(line RUNTIME_OVERRIDE | sed 's/: .*//')" = "profile $r names no runtime (claude-code), resolved in fakecx" ]; } \
    && ok "role-$r-override-extra" || no "the $r role against the project's own runtime: rc=$PREP_RC $PREP"
  prep wt --slug "${r}c" --role "$r" --runtime claude-code
  { [ "$PREP_RC" = 0 ] && [ "$(line RUNTIME)" = claude-code ] && [ "$(line PROFILE)" = "$r" ] && ! grep -q RUNTIME_OVERRIDE <<<"$PREP"; } \
    && ok "role-$r-silent-own" || no "the $r role with the project's own runtime as an option: rc=$PREP_RC $PREP"
done

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
setline "$CMDOWN" '.model_confirmed = true | .model = "other-model"'
READY "$CMDOWN" >/dev/null && ok model-confirmed-not-compared || no "a flipped model_confirmed (or another model) must not fail the agreement: $(READY "$CMDOWN")"
setline "$CMDOWN" '.runtime = "fakecx"'
out=$(READY "$CMDOWN"); rc=$?
{ [ "$rc" != 0 ] && grep -q 'prepared command request disagrees with lead registry' <<<"$out"; } && ok agreement-compares-runtime || no "a line whose runtime was changed must fail: rc=$rc $out"
setline "$CMDOWN" '.runtime = "fakeown"'

# --- local run starts a run on the runtime it was prepared for: the registry line names it, the mirrors say so, and the lead's project is the one asked
dispatch() { printf 'TASK: change the thing\nDONE: it is changed\n' > "$RUN/task.md"; "$DA" local run "$RUN" "$@" 2>&1; }
prep two --slug u1 --profile cx-build --runtime fakever
out=$(dispatch); rc=$?
{ [ "$rc" = 0 ] && jq -e '.runtime == "fakever" and .class == "write"' "$RUN/dispatch.json" >/dev/null && jq -e '.runtime == "fakever"' "$RUN/request.json" >/dev/null \
  && [ "$($LC -C "$RUN/clone" log -1 --format=%s)" = "Stub: a file" ]; } && ok run-on-extra-runtime || no "a run on the extra runtime: rc=$rc $out"
RUNX=$RUN
prep two --slug u2 --runtime fakecx
out=$(dispatch --dry-run); rc=$?
{ [ "$rc" = 0 ] && grep -q '^ARGV=\["fakecx","exec"' <<<"$out"; } && ok run-dry-names-command-of-runtime || no "dry run on the extra runtime: rc=$rc $out"

# --- a run prepared for a runtime that the project no longer enables, or that can no longer be used, or that changed since, is refused (drift), and starts nothing
prep two --slug d1 --runtime fakedis
jq '.models.extra_runtimes.local -= ["fakedis"]' "$T/c/projects/two.json" > "$T/two.json" && mv "$T/two.json" "$T/c/projects/two.json"
out=$(dispatch); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-drift ] && grep -q 'name=fakedis why=not-enabled' <<<"$out" && [ -z "$($LC -C "$RUN/clone" log origin/main..HEAD --format=%s)" ] && [ ! -e "$RUN/dispatch.json" ]; } \
  && ok drift-disabled || no "a run of a disabled runtime: rc=$rc $out"
prep two --slug d2 --runtime fakechg
jq '.dispatch.timeout_s = 77' "$TOOL/lib/providers/fakechg.json" > "$T/chg.json" && mv "$T/chg.json" "$TOOL/lib/providers/fakechg.json"
out=$(dispatch); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-drift ] && grep -q 'name=fakechg why=changed' <<<"$out" && grep -q 're-prepare' <<<"$out" && [ ! -e "$RUN/dispatch.json" ]; } \
  && ok drift-changed || no "a run of a runtime changed since prepare: rc=$rc $out"
prep two --slug d3 --runtime fakeuse
jq '.dispatch.mode = "in-session"' "$TOOL/lib/providers/fakeuse.json" > "$T/use.json" && mv "$T/use.json" "$TOOL/lib/providers/fakeuse.json"
out=$(dispatch); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-drift ] && grep -q 'name=fakeuse why=not-usable' <<<"$out"; } && ok drift-unusable || no "a run of a runtime no longer usable: rc=$rc $out"

# --- a run of the project's own runtime is never drift for an extra runtime's sake, and an in-session own run is still not started by qargi
prep two --slug o1
out=$(dispatch); rc=$?
{ [ "$rc" = 2 ] && grep -q 'dispatches in the lead.s own session' <<<"$out" && ! grep -q 'runtime-drift' <<<"$out"; } && ok insession-run-refused-as-before || no "an in-session run of a project with extras: rc=$rc $out"
prep cmd --slug o2
out=$(dispatch --dry-run); rc=$?
{ [ "$rc" = 0 ] && grep -q '^ARGV=\["fakeown","exec"' <<<"$out"; } && ok run-own-command-runtime || no "a run of the own command runtime: rc=$rc $out"

# --- the views: local list has a RUNTIME column and review check a runtime= line, from the registry line, with the model as asked for (never "confirmed")
LIST=$("$DA" local list 2>&1)
{ grep -q '^ROLE  *SLUG  *AGE  *APPLIED  *MERGED  *RUNTIME  *RUN$' <<<"$LIST" \
  && grep -E "^build +u1 .* fakever +$RUNX  model=gpt-6.1-terra \(requested, override verified\)\$" <<<"$LIST" >/dev/null \
  && grep -E "^build +u2 .* fakecx +$T/scr/qargi\.[A-Za-z0-9]{6}  model=gpt-6.1-terra \(requested, not confirmed\)\$" <<<"$LIST" >/dev/null \
  && grep -E "^build +o1 .* claude-code +$T/scr/qargi\.[A-Za-z0-9]{6}\$" <<<"$LIST" >/dev/null; } \
  && ok list-runtime-column || no "local list: $LIST"
out=$("$DA" review check "$RUNX/out" 2>&1)
grep -qx 'runtime=fakever model=gpt-6.1-terra (requested, override verified)' <<<"$out" && ok override-verified-wording || no "review check, a verified override: $out"
RUNCX=$(sed -n 's/^build  *u2 .* \(\/[^ ]*qargi\.[A-Za-z0-9]*\)  model=.*/\1/p' <<<"$LIST")
out=$("$DA" review check "$RUNCX/out" 2>&1)
grep -qx 'runtime=fakecx model=gpt-6.1-terra (requested, not confirmed)' <<<"$out" && ok review-check-not-confirmed || no "review check, an unverified override: $RUNCX $out"
RUNO1=$(sed -n 's/^build  *o1 .* \(\/[^ ]*qargi\.[A-Za-z0-9]*\)$/\1/p' <<<"$LIST")
out=$("$DA" review check "$RUNO1/out" 2>&1)
{ grep -qx 'runtime=claude-code' <<<"$out" && ! grep -q 'confirmed\|verified' <<<"$out"; } && ok review-check-insession-runtime || no "review check, an in-session run: $RUNO1 $out"

# --- provider notes --run reads the runtime the registry line of a prepared run records: a run on an extra runtime is started by qargi local run, a run of the in-session own runtime
# by the session's tool; the line is the one prepare wrote, not a line written by hand
out=$("$DA" provider notes spawn --run "$RUNX" --project two 2>&1)
{ grep -q 'qargi local run RUN' <<<"$out" && ! grep -q 'Agent tool' <<<"$out"; } && ok notes-run-extra-runtime || no "provider notes spawn --run, a run on an extra runtime: $out"
out=$("$DA" provider notes spawn --run "$RUNO1" --project two 2>&1)
{ grep -q 'Agent tool' <<<"$out" && ! grep -q 'qargi local run RUN' <<<"$out"; } && ok notes-run-own-runtime || no "provider notes spawn --run, a run of the own runtime: $out"

# --- an open run prepared before the project had extra runtimes keeps its line as written: after the enable it still starts on the project's own runtime, is not
# stale, shows "-" in the list and no runtime= line in review check
mkproj late '{"local":"fakeown"}' null null "$ACC"
prep late --slug e1
LATE=$RUN
{ ! regline "$LATE" | jq -e 'has("runtime")' >/dev/null; } && ok registry-no-extras-no-key || no "the line of a project without extras: $(regline "$LATE")"
jq '.models.extra_runtimes = {local: ["fakecx"]}' "$T/c/projects/late.json" > "$T/late.json" && mv "$T/late.json" "$T/c/projects/late.json"
printf 'TASK: x\nDONE: y\n' > "$LATE/task.md"; out=$("$DA" local run "$LATE" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^ARGV=\["fakeown","exec"' <<<"$out" && READY "$LATE" >/dev/null; } && ok open-run-before-enable || no "an open run prepared before the enable: rc=$rc $out"
LIST=$("$DA" local list 2>&1)
grep -E " - +$LATE\$" <<<"$LIST" >/dev/null && ok list-run-before-enable-dash || no "local list, a run prepared before the enable: $LIST"
out=$("$DA" review check "$LATE/out" 2>&1)
! grep -q '^runtime=' <<<"$out" && ok review-check-no-runtime-line || no "review check, a run prepared before the enable: $out"

# --- verify, review, apply, close and clean never ask for the run's runtime: the same series returned by the project's own runtime and by an extra one gets the same
# answers from them after the extra runtime is disabled and its definition is gone (the runtime= line of review check is the one expected difference)
mkfake fakeinv
for r in fakeown fakeinv; do   # the stub's commit gets a message with a body, as review check asks
  sed -i 's/-m "Stub: a file"/-m "Stub: a file" -m "Adds a file, so that the series has a message that says what changed."/' "$TOOL/stubs/$r"
done
for x in a b c d; do mkproj "inv$x" '{"local":"fakeown"}' '["fakeinv"]' null "$ACC"; done   # one project and one repository for each run: an apply changes the refs the next verify compares
collect() { # RUN BASE: the series the member made, collected by hand as a member would: the patches, a manifest and the series note in OUT
  mkdir -p "$1/out/patches"
  $LC -C "$1/clone" format-patch -q -o "$1/out/patches" "$2..HEAD"
  git -C "$1/clone" log --reverse --format='%H%x09%s' "$2..HEAD" | jq -R -s -c '[split("\n")[] | select(length > 0) | split("\t") | {sha: .[0], subject: .[1]}] as $c
    | {status: "DONE", commits: $c, commit_advice: ($c | map(. + {why_separate: "x", depends_on: [], builds_alone: true})), patch_groups: [{name: "stub", why: "one change", commits: ($c | map(.sha))}]}' > "$1/out/manifest.json"
  echo "# series" > "$1/out/series.md"
}
mkseries() { # SLUG [prepare options]: prepare a build run in project inv<last letter of the slug>, start it and collect what the stub committed: RUN
  local slug=$1 base
  shift
  prep "inv${slug#i}" --slug "$slug" "$@"
  [ "$PREP_RC" = 0 ] || no "invariance: prepare $slug: $PREP"
  base=$(line BASE_SHA)
  out=$(dispatch) || no "invariance: run $slug: $out"
  collect "$RUN" "$base"
}
mkseries ia;                    RA=$RUN       # the project's own runtime
mkseries ib --runtime fakeinv;  RB=$RUN       # an extra one
mkseries ic;                    RC=$RUN
mkseries id --runtime fakeinv;  RD=$RUN
for x in a b c d; do
  jq '.models.extra_runtimes.local = []' "$T/c/projects/inv$x.json" > "$T/inv.json" && mv "$T/inv.json" "$T/c/projects/inv$x.json"
done
rm -rf "$TOOL/lib/providers/fakeinv.json" "$TOOL/lib/providers/fakeinv" "$TOOL/stubs/fakeinv"
{ ! "$DA" provider runtimes invb 2>&1 | grep -q fakeinv; [ ! -e "$TOOL/lib/providers/fakeinv.json" ]; } || no "invariance: the runtime is still there"
invmask() { # RUN: what a verb printed with the names that differ from one run to the next masked (the run, the series' commit ids, the slug)
  sed -e "s#$1#RUN#g" -e "s#$T#T#g" -e 's/[0-9a-f]\{40\}/SHA/g' -e 's/[0-9a-f]\{7,12\}/ID/g' -e 's/qargi\.[A-Za-z0-9]\{6\}/qargi.XXXXXX/g' -e 's/qargi-run\.[A-Za-z0-9]\{6\}/qargi-run.XXXXXX/g' -e 's/\binv[a-d]\b/PROJ/g' -e 's/\bi[a-d]\b/SLUG/g'
}
invops() { # RUN PROJECT: verify, review check and apply, each with its exit status, masked
  local op
  for op in "local verify $1" "review check $1/out" "review apply $1 --project $2"; do
    echo "--- ${op%% $1*}"; "$DA" $op 2>&1 | invmask "$1"; echo "exit ${PIPESTATUS[0]}"
  done
}
invops2() { # RUN: verify, close (the patches were applied by hand) and clean
  local op
  for op in "local verify $1" "local close $1 --applied-by-am" "local clean $1"; do
    echo "--- ${op%% $1*}"; "$DA" $op 2>&1 | invmask "$1"; echo "exit ${PIPESTATUS[0]}"
  done
}
invops "$RA" inva > "$T/inv-a.out"; invops "$RB" invb > "$T/inv-b.out"
invops2 "$RC" > "$T/inv-c.out"; invops2 "$RD" > "$T/inv-d.out"
INVCASES_A=$(grep -c . "$T/inv-a.out")
diff <(grep -v '^runtime=' "$T/inv-b.out") <(grep -v '^runtime=' "$T/inv-a.out") >"$T/inv-ab.diff" 2>&1; ab=$?
diff "$T/inv-c.out" "$T/inv-d.out" >"$T/inv-cd.diff" 2>&1; cd=$?
{ [ "$ab" = 0 ] && [ "$cd" = 0 ] && ! grep -q '^exit [1-9]' "$T/inv-a.out" "$T/inv-c.out" && [ "$INVCASES_A" -gt 6 ] \
  && grep -q '^runtime=fakeinv ' "$T/inv-b.out" && grep -q '^runtime=fakeown ' "$T/inv-a.out"; } \
  && ok invariance || no "invariance: verify, check, apply, close and clean differ for the extra runtime: $(cat "$T/inv-ab.diff" "$T/inv-cd.diff") | $(cat "$T/inv-a.out")"

# --- a reading review: a read-only run on an extra runtime gets the read-only sandbox and no directory the member may write, whatever the profile says
prep two --slug v1 --role review --runtime fakecx
out=$(dispatch --dry-run); rc=$?
argv=$(sed -n 's/^ARGV=//p' <<<"$out")
{ [ "$rc" = 0 ] && jq -e 'index("--sandbox") as $i | $i != null and .[$i + 1] == "read-only" and (index("workspace-write") == null) and (index("--add-dir") == null)' <<<"$argv" >/dev/null; } \
  && ok reading-review-read-only || no "a read-only run on an extra runtime: rc=$rc $out"
prep two --slug v2 --role review --profile cx-review
out=$(dispatch --dry-run); rc=$?
argv=$(sed -n 's/^ARGV=//p' <<<"$out")
{ [ "$rc" = 0 ] && [ "$(line RUNTIME)" = fakecx ] && jq -e 'index("--sandbox") as $i | $i != null and .[$i + 1] == "read-only" and (index("workspace-write") == null) and (index("--add-dir") == null)' <<<"$argv" >/dev/null; } \
  && ok reading-review-by-profile || no "a read-only run by a profile of an extra runtime: rc=$rc $out"

exit $fail
